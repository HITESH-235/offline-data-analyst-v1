"""Offline captured-provider replay of the single deterministic request path."""
import copy
import json
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.api.v1.chat import process_chat_message
from app.api.v1.projects import list_saved_analyses
from app.models.chat import ChatRequest, DBChatHistory
from app.models.project import DBProject
from app.services.analysis_context import load_context
from app.services.dataset_manager import DatasetManager
from app.services import planned_analysis
from app.storage.sqlite.session import Base
from app.core.config import settings
from app.analysis.operations import validate_plan, planner_instructions, ContractError

ROOT=Path(settings.WORKSPACE_DIR)/'evaluations/quick-review-2026-11-10'
def captured(key):return json.loads((ROOT/(key+'.json')).read_text())
def drafts(key):return [a['output'] for a in captured(key)['result']['planner_diagnostics']]

class ConsolidationReplay(unittest.TestCase):
    def setUp(self):
        self.engine=create_engine('sqlite://');Base.metadata.create_all(self.engine);self.db=Session(self.engine)
        self.db.add(DBProject(id='replay',name='Replay'));self.db.commit()
    def tearDown(self):self.db.close();self.engine.dispose()
    def send(self,key,replies=None,question=None):
        case=captured(key)['case'];stages=[]
        with patch('app.llm.client.OllamaClient.call_model',side_effect=[json.dumps(r) for r in (replies or drafts(key))]) as model,patch('app.llm.agent.Agent.run',side_effect=AssertionError('Deterministic requests must not enter Agent')),patch.object(planned_analysis,'run',wraps=planned_analysis.run) as coordinator,patch('app.llm.table_selector.TableSelector.select_tables',side_effect=AssertionError('Plan owns source selection')):
            r,failed=process_chat_message(ChatRequest(project_id='replay',dataset_id=case['dataset'],message=question or case['question']),self.db,stages.append)
        self.assertLessEqual(model.call_count,2)
        if r.get('analysis_status')=='complete':
            self.assertEqual(coordinator.call_count,1)
            self.assertEqual(stages.count('validating'),1);self.assertEqual(stages[-1],'publishing')
            saved=json.loads(self.db.get(DBChatHistory,r['id']).metadata_json)
            self.assertEqual(saved['analysis_context'],{'version':1,'plan':r['analysis_plan']})
            self.assertEqual(next(v for v in list_saved_analyses('replay',self.db) if v['id']==r['id'])['analysisPackage'],r['analysis_package'])
        return r,failed
    def oracle(self,key):
        case=captured(key)['case']
        with sqlite3.connect(DatasetManager.get_dataset(None,case['dataset']).filepath) as db:return db.execute(case['sql']).fetchall()
    def assert_sql(self,key,result):
        self.assertEqual(result['analysis_status'],'complete',result['content']);r=result['results'];expected=self.oracle(key)
        self.assertEqual(len(r['data']),len(expected))
        if key.startswith('G'):
            got={x['customer_state']:x for x in r['comparison_audit']['groups']}
            for state,n,count,pct in expected:
                self.assertEqual((got[state]['comparable_count'],got[state]['matched_count']),(n,count));self.assertAlmostEqual(got[state]['percentage'],pct,places=8)
            pcol=next(c for c,u in r['units'].items() if u=='%');values=[row[pcol] for row in r['data']];self.assertEqual(values,sorted(values,reverse=True))
            self.assertEqual(r['comparison_audit']['missing_actual_count'],8 if key=='G01' else 6)
            self.assertEqual(r['comparison_audit']['missing_comparison_count'],0)
            self.assertIsNone(r['result_scope']['limit'])
        elif key in ['Q03','Q04']:
            for row,(_,_,value) in zip(r['data'],expected):self.assertAlmostEqual(row['Net Sales'],value,places=6)
        else:
            got={row[r['columns'][0]]:row[r['columns'][1]] for row in r['data']}
            for group,value in expected:self.assertAlmostEqual(got[group],value,places=6)
        self.assertNotIn('| ---',result['content'])
    def test_original_drafts_execute_once_and_match_independent_sql(self):
        for key in ['G01','Q02','Q03','Q07','Q08']:
            with self.subTest(case=key):
                r,failed=self.send(key);self.assertFalse(failed,r['content']);self.assert_sql(key,r)
                if key in ['Q07','Q08']:self.assertTrue(r['analysis_package']['charts'])
                if key=='Q08':self.assertGreater(r['results']['row_count'],10);self.assertEqual(r['analysis_package']['chart_scope']['top_n'],10)
    def test_success_then_history_reload_and_followups(self):
        first,failed=self.send('G01');self.assertFalse(failed,first['content']);self.db.close();self.db=Session(self.engine)
        follow=copy.deepcopy(drafts('G02')[0]);follow['reference_message_id']=first['id'];follow['changed_fields']=['eligibility_filters']
        follow['analysis_plan']['chart_scope']=copy.deepcopy(first['analysis_plan'].get('chart_scope') or {})
        follow['analysis_plan']['outputs'][0]['id']=first['analysis_plan']['outputs'][0]['id']
        for field in ('matched_label','count_label','comparison_label'):
            follow['analysis_plan']['outputs'][0]['parameters'][field]=first['analysis_plan']['outputs'][0]['parameters'][field]
        r,failed=self.send('G02',[follow]);self.assertFalse(failed,r['content']);self.assert_sql('G02',r)
        self.db.close();self.db=Session(self.engine)
        overall={'intent':'SIMPLE','context_action':'inherit','reference_message_id':r['id'],
                 'analysis_plan':copy.deepcopy(r['analysis_plan'])}
        # The scalar follow-up no longer requests the prior breakdown chart.
        # Declare that change; completion must still reject an unmet chart request.
        overall['changed_fields']=['group_by','sort_by','ascending','chart_scope']
        overall['analysis_plan']['chart_scope']={'required':False,'top_n':10}
        overall['analysis_plan']['outputs'][0]['parameters']['group_by']=[]
        overall['analysis_plan']['outputs'][0]['parameters'].pop('sort_by',None)
        overall['analysis_plan']['outputs'][0]['parameters'].pop('ascending',None)
        scalar,failed=self.send('G03',[overall]);self.assertFalse(failed,scalar['content'])
        audit=scalar['results']['comparison_audit']
        self.assertEqual((audit['comparable_count'],audit['matched_count'],audit['missing_actual_count']),(52777,4078,6))
        self.assertAlmostEqual(audit['percentage'],100*4078/52777,places=8)
        # A new standalone request must discard the prior year's filter.
        r,failed=self.send('G01');self.assertFalse(failed,r['content']);self.assert_sql('G01',r)
        first,failed=self.send('Q03');self.assertFalse(failed,first['content']);self.db.close();self.db=Session(self.engine)
        follow={'intent':'SIMPLE','context_action':'inherit','reference_message_id':first['id'],
                'changed_fields':['grain'],'analysis_plan':copy.deepcopy(first['analysis_plan'])}
        follow['analysis_plan']['outputs'][0]['parameters']['grain']='quarter'
        r,failed=self.send('Q04',[follow]);self.assertFalse(failed,r['content']);self.assert_sql('Q04',r)
    def test_clarify_unsupported_and_unverifiable_python_do_not_execute(self):
        for key,status in [('G03','clarification'),('Q12','unsupported'),('R01','unsupported')]:
            with self.subTest(case=key):
                r,failed=self.send(key);self.assertEqual(r.get('analysis_status'),status,r['content']);self.assertNotIn('results',r)
    def test_independent_expected_specs_detect_reduced_calculations(self):
        from test_single_specification import same_spec
        for key,field in [('Q03','formula'),('Q07','conversion'),('Q08','conversion'),('G01','population'),('G01','sorting')]:
            plan=copy.deepcopy(drafts(key)[-1]);plan.pop('request_requirements',None);p=plan['analysis_plan']['outputs'][0]['parameters']
            if field=='formula':p['metric']['expression']={'column':'UnitPrice'}
            elif field=='conversion':p['transforms'][0]['divide_by']=1
            elif field=='population':p['eligibility_filters']=[]
            else:p['sort_by']='matched_count'
            self.assertFalse(same_spec(drafts(key)[-1],plan))
    def test_schema_has_one_executable_representation(self):
        schema=json.loads(planner_instructions().split('Envelope schema:\n')[1])
        for name in ['resolved_analysis','resolved_query','operation','completion_contract']:self.assertNotIn(name,schema['properties'])
        self.assertEqual(schema['allOf'][0]['then']['properties']['request_requirements'],{'type':'null'})
        for name in ['resolved_analysis','resolved_query','operation','completion_contract']:
            with self.subTest(name=name),self.assertRaises(ValueError):validate_plan({'intent':'SIMPLE',name:{}})
