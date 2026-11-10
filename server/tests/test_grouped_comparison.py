import copy
import json
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.analysis.operations import execute, matches, validate_plan, ContractError
from app.api.v1.chat import process_chat_message
from app.api.v1.projects import list_saved_analyses
from app.models.chat import ChatRequest, DBChatHistory
from app.models.project import DBProject
from app.services.analysis_context import load_context
from app.services.analysis_package import finalize, OutputAccumulator
from app.services.dataset_manager import DatasetManager
from app.services.metadata_service import MetadataService
from app.services.request_requirements import validate_plan_request, RequestIncomplete
from app.storage.sqlite.session import Base

CAPTURE=json.loads((Path(__file__).parent/'fixtures/grouped_comparison_reduced_response.json').read_text())
SOURCE=CAPTURE['planner_output']['analysis_plan']['source']
PARAMS={'column':'order_delivered_customer_date','value_column':'order_estimated_delivery_date',
        'operator':'>','value_type':'date','date_part':'date','matched_label':'Late','count_label':'Orders',
        'comparison_label':'Estimated','group_by':['customer_state'],'sort_by':'percentage','ascending':False,
        'eligibility_filters':[{'column':'order_status','operator':'==','value':'delivered'}]}
PLAN={'intent':'SIMPLE','context_action':'standalone','analysis_plan':{'source':SOURCE,
      'outputs':[{'id':'state_delivery','kind':'comparison_summary','parameters':PARAMS}]}}

class GroupedComparisonTest(unittest.TestCase):
    def setUp(self):
        self.frame=pd.DataFrame({'customer_state':['A','A','B','B','C','C','D',None],
            'order_status':['delivered']*7+['cancelled'],
            'order_delivered_customer_date':['2020-01-01 23:59:59','2020-01-01', '2020-01-03',None,'2020-01-01',None,'2020-01-03','2020-01-03'],
            'order_estimated_delivery_date':['2020-01-01','2020-01-01','2020-01-01',None,None,'2020-01-02','2020-01-01','2020-01-01']})
    def test_masks_zero_events_missing_dates_zero_denominator_and_null_sort(self):
        r=execute('comparison_summary',PARAMS,self.frame)
        self.assertEqual(r['columns'],['customer_state','Comparable Orders','Late Orders','Late Percentage','Missing Actual Date','Missing Estimated Date'])
        self.assertEqual([x['customer_state'] for x in r['data']],['B','D','A','C'])
        rows={x['customer_state']:x for x in r['data']}
        self.assertEqual(rows['A']['Late Orders'],0);self.assertEqual(rows['A']['Comparable Orders'],2)
        self.assertIsNone(rows['C']['Late Percentage']);self.assertEqual(rows['C']['Missing Estimated Date'],1)
        self.assertEqual(rows['B']['Missing Estimated Date'],0)  # both dates absent is counted as missing actual only
        self.assertEqual(r['comparison_audit']['missing_actual_count'],2)
        self.assertEqual(r['comparison_audit']['missing_comparison_count'],1)
        self.assertTrue(matches('comparison_summary',PARAMS,r))
        asc=execute('comparison_summary',{**PARAMS,'ascending':True},self.frame)
        self.assertEqual([x['customer_state'] for x in asc['data']],['A','B','D','C'])
        modified=copy.deepcopy(r);modified['data'][0]['Late Percentage']=0
        self.assertFalse(matches('comparison_summary',PARAMS,modified))
    def test_general_numeric_comparison_multiple_groups_null_group_and_empty(self):
        df=pd.DataFrame({'region':['x','x',None],'site':['a','b','c'],'reading':[2,0,1],'threshold':[1,1,1]})
        p={'column':'reading','value_column':'threshold','operator':'>','group_by':['region','site'],'sort_by':'percentage'}
        r=execute('comparison_summary',p,df)
        self.assertEqual(r['row_count'],3);self.assertIn(None,[row['region'] for row in r['data']])
        self.assertEqual(execute('comparison_summary',p,df.iloc[:0])['data'],[])
        for bad in [{**p,'group_by':['missing']},{**p,'limit':2},{**p,'group_by':['region','region']}]:
            with self.assertRaises(ValueError):execute('comparison_summary',bad,df)
    def test_duplicate_index_does_not_change_population(self):
        self.frame.index=[0]*len(self.frame)
        r=execute('comparison_summary',PARAMS,self.frame)
        self.assertEqual(r['comparison_audit']['comparable_count'],4)

class GroupedComparisonRouteTest(unittest.TestCase):
    def setUp(self):
        self.engine=create_engine('sqlite://');Base.metadata.create_all(self.engine);self.db=Session(self.engine)
        self.db.add(DBProject(id='test',name='Test'));self.db.commit()
        self.profile=MetadataService.get_profile('olist.db::orders')
        from app.analysis.operations import output_contract
        self.requirements=output_contract(PLAN['analysis_plan'])
    def tearDown(self):self.db.close();self.engine.dispose()
    def send(self,plan,question=None):
        with patch('app.llm.client.OllamaClient.call_model',return_value=json.dumps(plan)) as model, patch('app.llm.agent.OllamaClient.call_model_chat') as agent:
            r,failed=process_chat_message(ChatRequest(project_id='test',dataset_id='olist.db::orders',message=question or CAPTURE['question']),self.db,lambda s:None)
        self.assertEqual(model.call_count,1);agent.assert_not_called()
        return r,failed
    def test_complete_real_olist_join_matches_independent_sql_and_saved_package(self):
        r,failed=self.send(PLAN);self.assertFalse(failed,r['content'])
        result=r['results'];rows=result['data'];self.assertEqual(len(rows),27)
        with sqlite3.connect(DatasetManager.get_dataset(None,'olist.db::orders').filepath) as db:
            expected=db.execute('''SELECT c.customer_state,
              SUM(o.order_delivered_customer_date IS NOT NULL AND o.order_estimated_delivery_date IS NOT NULL),
              SUM(CASE WHEN date(o.order_delivered_customer_date)>date(o.order_estimated_delivery_date) THEN 1 ELSE 0 END),
              SUM(o.order_delivered_customer_date IS NULL),
              SUM(o.order_delivered_customer_date IS NOT NULL AND o.order_estimated_delivery_date IS NULL)
              FROM orders o JOIN customers c ON o.customer_id=c.customer_id
              WHERE o.order_status='delivered' GROUP BY c.customer_state''').fetchall()
        by_state={row[0]:row[1:] for row in expected}
        for row in rows:
            n,count,missing,estimated=by_state[row['customer_state']]
            self.assertEqual((row['Comparable Orders'],row['Late Orders'],row['Missing Actual Date'],row['Missing Estimated Date']),(n,count,missing,estimated))
            self.assertAlmostEqual(row['Late Percentage'],100*count/n)
        self.assertEqual([row['customer_state'] for row in rows[:3]],['AL','MA','SE'])
        for text in ['6.773090%','6,534','96,470','AL','21.410579%','MA','17.433752%','SE','15.223881%']:
            self.assertIn(text,r['content'])
        self.assertNotIn('|',r['content']);self.assertNotIn('remaining rows',r['content'])
        self.assertEqual(sum(row['Missing Actual Date'] for row in rows),8)
        pack=r['analysis_package'];self.assertEqual(len(pack['tables']),1)
        self.assertEqual(pack['charts'][0]['table_id'],pack['tables'][0]['id'])
        self.assertEqual(pack['charts'][0]['specification']['y'],'Late Percentage')
        self.assertTrue(all(c['status']=='passed' for c in pack['completion_checks']))
        self.assertTrue(any(c['requirement_id']==PLAN['analysis_plan']['outputs'][0]['id'] for c in pack['completion_checks']))
        saved=list_saved_analyses('test',self.db)[0];self.assertEqual(saved['analysisPackage'],pack)
        self.assertEqual(saved['result'],result)
    def test_planner_can_echo_full_typed_request_requirements_in_same_call(self):
        plan=copy.deepcopy(PLAN);plan['request_requirements']=self.requirements
        validate_plan(plan)
        r,failed=self.send(plan);self.assertFalse(failed,r['content'])
        self.assertTrue(all(c['status']=='passed' for c in r['analysis_package']['completion_checks']))
    def test_captured_reduced_plan_fails_independent_expected_specification(self):
        with self.assertRaises(RequestIncomplete):validate_plan_request(CAPTURE['planner_output'],self.requirements)
    def test_captured_outputs_cannot_complete_reduced_requirements_at_publication(self):
        pack=CAPTURE['analysis_package']
        raw={'analysis_outputs':{'tables':pack['tables'],'charts':[],'observations':[]},'calculation':CAPTURE['calculation']}
        final=finalize(raw,CAPTURE['question'],'test','replay',pack['requirements'],request_requirements=self.requirements)
        self.assertEqual(final['analysis_status'],'incomplete');self.assertNotIn('|',final['content'])
        self.assertTrue(any(c['requirement_id']==PLAN['analysis_plan']['outputs'][0]['id'] and c['status']=='missing' for c in final['analysis_package']['completion_checks']))
    def test_plan_drift_in_formula_population_grouping_sort_source_and_table_limit(self):
        for key,value in [('group_by',[]),('sort_by','matched_count'),('ascending',True),('operator','>='),('eligibility_filters',[]),('date_part',None)]:
            bad=copy.deepcopy(PLAN);bad['analysis_plan']['outputs'][0]['parameters'][key]=value
            with self.subTest(key=key), self.assertRaises(RequestIncomplete):validate_plan_request(bad,self.requirements)
        bad=copy.deepcopy(PLAN);bad['analysis_plan']['source']['tables'].append('olist.db::items')
        with self.assertRaises(RequestIncomplete):validate_plan_request(bad,self.requirements)
    def test_explicit_table_in_chat_is_honored(self):
        plan=copy.deepcopy(PLAN);plan['analysis_plan']['presentation']={'table_in_chat':True}
        r,failed=self.send(plan,CAPTURE['question']+' Show the table in chat.')
        self.assertFalse(failed,r['content']);self.assertIn('| customer_state |',r['content'])
        self.assertEqual(r['content'].count('| AL |'),1)
