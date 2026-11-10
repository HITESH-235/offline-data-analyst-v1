"""Bounded staged aggregation: real sources, independent SQLite, no external calls."""
import copy
import json
import sqlite3
import tempfile
import unittest
import asyncio
import threading
import time
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import Session,sessionmaker
from app.analysis.operations import execute,validate,validate_plan,matches,guard_repair,planner_instructions
from app.api.v1.chat import process_chat_message,handle_chat_message
from app.api.v1.projects import list_saved_analyses
from app.models.chat import ChatRequest,DBChatHistory
from app.models.project import DBProject
from app.services import planned_analysis
from app.services.analysis_context import load_context
from app.services.analysis_package import OutputAccumulator,finalize
from app.services.dataset_manager import DatasetManager
from app.services.metadata_service import MetadataService
from app.services.request_requirements import validate_plan_request,RequestIncomplete
from app.core.config import settings
from app.storage.sqlite.session import Base

ROOT=Path(settings.WORKSPACE_DIR)/'evaluations/single-specification-2026-11-10'
FIXTURE=json.loads((Path(__file__).parent/'fixtures/entity_comparison_plan.json').read_text());QUESTION=FIXTURE['question'];PLAN=FIXTURE['plan'];PARAMS=PLAN['analysis_plan']['outputs'][0]['parameters']
# The oracle deliberately uses independent SQL, not the Python operation.
ORACLE='''WITH per_entity AS (SELECT order_id,COUNT(*) AS records,COUNT(review_score) AS usable,AVG(review_score) AS mean_score FROM order_reviews GROUP BY order_id), eligible AS (SELECT o.*,r.records,r.usable,r.mean_score FROM orders o LEFT JOIN per_entity r ON o.order_id=r.order_id WHERE o.order_status='delivered' AND date(o.order_purchase_timestamp)>='2018-01-01' AND date(o.order_purchase_timestamp)<'2019-01-01') SELECT CASE WHEN date(order_delivered_customer_date) IS NULL THEN 'Missing actual' WHEN date(order_estimated_delivery_date) IS NULL THEN 'Missing comparison' WHEN date(order_delivered_customer_date)>date(order_estimated_delivery_date) THEN 'Late' ELSE 'On time' END AS classification,COUNT(*) AS comparable,COUNT(mean_score) AS contributing,AVG(mean_score) AS mean_score,SUM(records IS NULL) AS missing_records,SUM(records IS NOT NULL AND usable=0) AS unusable FROM eligible GROUP BY 1'''

class OfflineTest(unittest.TestCase):
    def setUp(self):
        for target in ['urllib.request.urlopen','urllib.request.OpenerDirector.open']:
            p=patch(target,side_effect=AssertionError('External calls blocked'));p.start();self.addCleanup(p.stop)

class EntityComparisonMath(OfflineTest):
    def setUp(self):
        super().setUp()
        self.p={'population_table':'devices','observations_table':'readings','entity_key':'device_key','observation_key':'device_ref','measurement':{'name':'Average temperature','expression':{'column':'temperature'},'unit':'degrees'},
          'comparison':{'column':'actual_date','value_column':'target_date','operator':'>','value_type':'date','date_part':'date'},'matched_label':'After','unmatched_label':'Within','entity_label':'Devices'}
        self.base=pd.DataFrame({'device_key':['a','b','c','d','e','f','g','h'],
          'actual_date':['2020-01-03','2020-01-04','2020-01-01 23:59:59','2020-01-04',None,'2020-01-04',None,'2020-01-04'],
          'target_date':['2020-01-01','2020-01-01','2020-01-01 00:00:00','2020-01-01','2020-01-01',None,None,'2020-01-01']})
        self.obs=pd.DataFrame({'device_ref':['a','b','b','b','c','d','d','e'],'temperature':[1.,3.,3.,3.,5.,None,None,9.]})
    def run_math(self,base=None,obs=None,p=None):return execute('entity_comparison',p or self.p,{'devices':self.base if base is None else base,'readings':self.obs if obs is None else obs})
    def test_equal_entity_weighting_duplicate_observations_nulls_and_missing_records(self):
        r=self.run_math();audit=r['entity_audit'];after=r['data'][0];within=r['data'][1]
        self.assertEqual(after['Average temperature'],2.) # (1 + 3)/2; raw-row mean would be 2.5
        self.assertEqual((after['Comparable Devices'],after['Contributing Devices'],after['Missing Measurement Devices']),(4,2,2))
        self.assertEqual(within['Average temperature'],5.) # same calendar day, different time
        self.assertEqual((audit['population_count'],audit['comparable_count'],audit['missing_actual_count'],audit['missing_comparison_count']),(8,5,2,1))
        self.assertEqual((audit['missing_record_count'],audit['unusable_measurement_count']),(1,1))
        self.assertEqual(audit['date_excluded_without_measurement_count'],2)
        self.assertTrue(matches('entity_comparison',self.p,r));self.assertEqual(audit['join']['joined_entities'],8)
        self.assertEqual(audit['first_stage']['observation_rows'],8)
        # Independently recompute the held-out example in SQLite.
        with sqlite3.connect(':memory:') as db:
            self.base.to_sql('devices',db,index=False);self.obs.to_sql('readings',db,index=False)
            expected=db.execute('''WITH means AS (SELECT device_ref,AVG(temperature) AS value FROM readings GROUP BY device_ref) SELECT AVG(m.value) FROM devices d LEFT JOIN means m ON d.device_key=m.device_ref WHERE date(actual_date)>date(target_date)''').fetchone()[0]
        self.assertAlmostEqual(after['Average temperature'],expected)
    def test_empty_groups_and_zero_contributors_remain_null(self):
        for base,obs in [(self.base.iloc[:0],self.obs.iloc[:0]),(self.base,self.obs.assign(temperature=None)),(self.base,self.obs.iloc[:0])]:
            with self.subTest(rows=len(base),observations=len(obs)):
                r=self.run_math(base,obs);self.assertEqual(len(r['data']),2)
                self.assertTrue(all(row['Average temperature'] is None for row in r['data']))
                a=OutputAccumulator();a.record('entity_comparison',self.p,r,{'tables':['devices','readings']},0,'staged')
                final=finalize({'analysis_outputs':a.export()},'Compare','p','r',{'outputs':[{'id':'staged','kind':'entity_comparison','parameters':self.p}]})
                self.assertEqual(final['analysis_status'],'complete',final['content']);self.assertEqual(final['analysis_package']['charts'],[])
    def test_invalid_keys_duplicates_and_measurements_are_rejected(self):
        cases=[(pd.concat([self.base,self.base.iloc[:1]]),self.obs),(self.base.assign(device_key=None),self.obs),
          (self.base,self.obs.assign(device_ref='unknown')),(self.base,self.obs.assign(device_ref=None)),
          (self.base,self.obs.assign(temperature='invalid')),(self.base,self.obs.assign(temperature=float('inf'))),
          (self.base.assign(device_key=range(8)),self.obs)]
        for base,obs in cases:
            with self.subTest(base_rows=len(base)),self.assertRaises(ValueError):self.run_math(base,obs)
        with self.assertRaises(ValueError):execute('entity_comparison',self.p,self.base.merge(self.obs,left_on='device_key',right_on='device_ref',how='left'))
    def test_expression_reuse_numeric_rule_and_unsupported_compositions(self):
        p=copy.deepcopy(self.p);p['measurement']['expression']={'op':'add','args':[{'column':'temperature'},{'value':2}]}
        self.assertEqual(self.run_math(p=p)['data'][0]['Average temperature'],4.)
        p['comparison']={'column':'actual_date','value_column':'target_date','operator':'>','value_type':'number'}
        base=self.base.assign(actual_date=[3,4,1,4,None,4,None,4],target_date=[1,1,1,1,1,None,None,1])
        self.assertEqual(self.run_math(base=base,p=p)['data'][0]['Average temperature'],4.)
        for field,value in [('weighting','observation_rows'),('group_aggregation','sum')]:
            bad={**self.p,field:value}
            with self.assertRaises(ValueError):validate('entity_comparison',bad)
        bad=copy.deepcopy(self.p);bad['measurement']['aggregation']='median'
        with self.assertRaises(ValueError):validate('entity_comparison',bad)
        bad=copy.deepcopy(self.p);bad['comparison']['operator']='>='
        with self.assertRaises(ValueError):validate('entity_comparison',bad)
    def test_result_and_audit_tampering_and_generated_tables_are_rejected(self):
        r=self.run_math()
        for target in ['data','audit','unit']:
            bad=copy.deepcopy(r)
            if target=='data':bad['data'][0]['Average temperature']=2.5
            elif target=='audit':bad['entity_audit']['contributing_count']=999
            else:bad['units']['Average temperature']='currency'
            self.assertFalse(matches('entity_comparison',self.p,bad))
            with self.assertRaises(ValueError):OutputAccumulator().record('entity_comparison',self.p,bad,{'tables':['devices','readings']},0)
        r.pop('operation_evidence')
        with self.assertRaisesRegex(ValueError,'native staged execution'):OutputAccumulator().record('entity_comparison',self.p,r,{'tables':['devices','readings']},0)

class EntityComparisonPipeline(OfflineTest):
    def setUp(self):
        super().setUp();self.engine=create_engine('sqlite://');Base.metadata.create_all(self.engine);self.db=Session(self.engine)
        self.db.add(DBProject(id='staged',name='Staged replay'));self.db.commit()
    def tearDown(self):self.db.close();self.engine.dispose()
    def send(self,plan=PLAN,question=QUESTION):
        with patch('app.llm.client.OllamaClient.call_model',return_value=json.dumps(plan)) as model,patch('app.llm.agent.Agent.run',side_effect=AssertionError('No alternate agent route')) as agent,patch.object(planned_analysis,'run',wraps=planned_analysis.run) as coordinator,patch('app.services.dataset_manager.DatasetManager.load_joined_dataframe',side_effect=AssertionError('No raw observation join')):
            result,failed=process_chat_message(ChatRequest(project_id='staged',dataset_id='olist.db::orders',message=question),self.db,lambda s:None)
        self.assertLessEqual(model.call_count,2);agent.assert_not_called()
        if not failed:self.assertEqual(model.call_count,1);self.assertEqual(coordinator.call_count,1)
        return result,failed
    def test_actual_olist_sql_oracle_complete_publication_and_saved_context(self):
        r,failed=self.send();self.assertFalse(failed,r['content']);audit=r['results']['entity_audit']
        with sqlite3.connect(Path(DatasetManager.get_dataset(None,'olist.db::orders').filepath).resolve().as_uri()+'?mode=ro',uri=True) as db:
            db.row_factory=sqlite3.Row;oracle=[dict(row) for row in db.execute(ORACLE)]
        want={v['classification']:v for v in oracle}
        for group in audit['groups']:
            expected=want[group['classification']]
            self.assertEqual((group['comparable_count'],group['contributing_count'],group['missing_record_count'],group['unusable_measurement_count']),
                             (expected['comparable'],expected['contributing'],expected['missing_records'],expected['unusable']))
            self.assertAlmostEqual(group['mean'],expected['mean_score'],places=12)
        self.assertEqual((audit['population_count'],audit['comparable_count'],audit['missing_actual_count'],audit['missing_comparison_count']),(52783,52777,6,0))
        self.assertEqual((audit['contributing_count'],audit['missing_record_count'],audit['unusable_measurement_count']),(52462,315,0))
        self.assertAlmostEqual(audit['groups'][0]['mean'],2.244366549824737,places=12)
        self.assertAlmostEqual(audit['groups'][1]['mean'],4.2983893152870625,places=12)
        self.assertIn('2.244367',r['content']);self.assertIn('4.298389',r['content']);self.assertIn('association',r['content']);self.assertNotIn('| ---',r['content'])
        self.assertEqual(r['analysis_package']['status'],'complete');self.assertTrue(all(c['status']=='passed' for c in r['analysis_package']['completion_checks']))
        self.db.close();self.db=Session(self.engine)
        saved=next(s for s in list_saved_analyses('staged',self.db) if s['id']==r['id']);self.assertEqual(saved['analysisPackage'],r['analysis_package'])
        context=load_context(self.db,'staged')['recent_successes'][0];self.assertEqual(context['analysis']['plan'],r['analysis_plan'])
        self.assertEqual(context['analysis']['plan']['outputs'][0]['parameters']['weighting'],'equal_entity')
        self.assertTrue(all(v>=0 for v in r['calculation']['steps'][0]['timings_ms'].values()))
        ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sqlite-execution.json').write_text(json.dumps({'question':QUESTION,'live_model_calls':0,'planner_reply':'typed fixture, not sampled from a live model','sql':ORACLE,'oracle':oracle,'result':r},indent=2)+'\n')
    def test_reduced_plan_wrong_measurement_filters_and_year_are_rejected(self):
        wrong=copy.deepcopy(PLAN);wrong['analysis_plan']['outputs'][0]={'id':'mean','kind':'aggregation','parameters':{'aggregations':{'review_score':'mean'},'group_by':[]}}
        variants=[wrong,{'intent':'COMPLEX','context_action':'standalone'}]
        for key,value in [('filters',[PARAMS['filters'][0]]),('entity_key','customer_id')]:
            p=copy.deepcopy(PLAN);p['analysis_plan']['outputs'][0]['parameters'][key]=value;variants.append(p)
        p=copy.deepcopy(PLAN);p['analysis_plan']['outputs'][0]['parameters']['measurement']['expression']={'value':1};variants.append(p)
        p=copy.deepcopy(PLAN);p['analysis_plan']['outputs'][0]['parameters']['filters'].append({'column':'order_delivered_customer_date','operator':'!=','value':None});variants.append(p)
        for plan in variants:
            with self.subTest(plan=plan):

                expected={'outputs':[{'id':'review_comparison','kind':'entity_comparison','parameters':PARAMS}]}
                with self.assertRaises((RequestIncomplete,ValueError)):validate_plan_request(plan,expected)
    def test_declared_relationships_and_extra_sources_are_rejected(self):
        for change in ['relationship','observation_key','extra_table']:
            plan=copy.deepcopy(PLAN)
            if change=='relationship':plan['analysis_plan']['source']['join_keys'][0]['from_column']='review_id'
            elif change=='observation_key':plan['analysis_plan']['outputs'][0]['parameters']['observation_key']='review_id'
            else:plan['analysis_plan']['source']['tables'].append('olist.db::order_items')
            r,failed=self.send(plan);self.assertTrue(failed);self.assertNotIn('results',r)
    def test_followup_after_reload_preserves_complete_specification(self):
        r,failed=self.send();self.assertFalse(failed,r['content']);self.db.close();self.db=Session(self.engine)
        follow=copy.deepcopy(PLAN);follow.update(context_action='inherit',reference_message_id=r['id'],changed_fields=['filters'])
        p=follow['analysis_plan']['outputs'][0]['parameters'];p['filters'][1]['value']='2017-01-01';p['filters'][2]['value']='2018-01-01'
        r,failed=self.send(follow,'Repeat that same comparison for purchases in 2017.');self.assertFalse(failed,r['content'])
        with sqlite3.connect(Path(DatasetManager.get_dataset(None,'olist.db::orders').filepath).resolve().as_uri()+'?mode=ro',uri=True) as db:
            expected=db.execute(ORACLE.replace('2018-01-01','2017-01-01').replace('2019-01-01','2018-01-01')).fetchall()
        by={row[0]:row for row in expected}
        for group in r['results']['entity_audit']['groups']:
            self.assertEqual(group['contributing_count'],by[group['classification']][2]);self.assertAlmostEqual(group['mean'],by[group['classification']][3],places=12)
        bad=copy.deepcopy(follow);bad['reference_message_id']=r['id'];bad['analysis_plan']['outputs'][0]['parameters']['comparison']['column']='order_delivered_carrier_date'
        result,failed=self.send(bad,'Repeat that same comparison.');self.assertTrue(failed);self.assertNotIn('results',result)
    def test_planner_schema_and_semantic_repair_do_not_drop_grain(self):
        schema=json.loads(planner_instructions().split('Envelope schema:\n')[1]);self.assertIn('Parameters_entity_comparison',schema['$defs'])
        original=copy.deepcopy(PLAN);original['analysis_plan']['outputs'][0]['parameters']['unknown']=True
        guard_repair(original,PLAN)
        for key,value in [('entity_key','customer_id'),('weighting','row_weighted')]:
            bad=copy.deepcopy(PLAN);bad['analysis_plan']['outputs'][0]['parameters'][key]=value
            with self.assertRaises(ValueError):guard_repair(original,bad)
    def test_total_deadline_fences_late_staged_result_and_preserves_history(self):
        # Real request path, isolated file DB and a controlled slow calculation.
        profile=MetadataService.get_profile('olist.db::orders');catalog=MetadataService.get_catalog_index()
        frames={name:DatasetManager.load_dataset_dataframe(DatasetManager.get_dataset(None,name)) for name in PLAN['analysis_plan']['source']['tables']}
        with tempfile.TemporaryDirectory() as root:
            engine=create_engine('sqlite:///'+root+'/history.db',connect_args={'check_same_thread':False});Base.metadata.create_all(engine);factory=sessionmaker(bind=engine)
            with factory() as db:db.add(DBProject(id='timeout',name='Timeout'));db.commit()
            started=threading.Event();release=threading.Event();finished=threading.Event();native=planned_analysis.execute
            def slow(*args):
                started.set();release.wait(3)
                try:return native(*args)
                finally:finished.set()
            request=ChatRequest(project_id='timeout',dataset_id='olist.db::orders',message=QUESTION)
            try:
                with patch('app.api.v1.chat.SessionLocal',factory),patch('app.api.v1.chat.MetadataService.get_profile',return_value=profile),patch('app.services.metadata_service.MetadataService.get_catalog_index',return_value=catalog),patch.object(DatasetManager,'load_dataset_dataframe',side_effect=lambda dataset:frames[dataset.id].copy()),patch.object(settings,'WORKSPACE_DIR',root),patch.object(settings,'CHAT_REQUEST_TIMEOUT_SECONDS',.5),patch('app.llm.client.OllamaClient.call_model',return_value=json.dumps(PLAN)),patch.object(planned_analysis,'execute',side_effect=slow):
                    result=asyncio.run(handle_chat_message(request));self.assertEqual(result.status_code,504)
                    self.assertTrue(started.is_set(),'deadline test must reach the staged calculation')
                    release.set()
                    self.assertTrue(finished.wait(3))
                    time.sleep(.05)
                    with factory() as db:self.assertEqual(db.query(DBChatHistory).filter_by(role='assistant').count(),0)
                    timings=[json.loads(p.read_text()) for p in Path(root,'evaluations/request-deadlines').glob('*.json')]
                    self.assertEqual(timings[0]['status'],'timed_out');self.assertTrue(timings[0].get('phases'))
            finally:release.set();engine.dispose()

class HeldOutSourcePipeline(OfflineTest):
    def test_declared_non_olist_sqlite_relationship_and_equal_weighting(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'plant.sqlite'
            with sqlite3.connect(path) as source:
                source.executescript('CREATE TABLE units(unit_ref TEXT PRIMARY KEY, observed_date TEXT, target_date TEXT); CREATE TABLE samples(owner_ref TEXT REFERENCES units(unit_ref), reading_value REAL);')
                source.executemany('INSERT INTO units VALUES (?,?,?)',[('u','2024-01-03','2024-01-01'),('v','2024-01-04','2024-01-01'),('w','2024-01-01 23:00:00','2024-01-01')])
                source.executemany('INSERT INTO samples VALUES (?,?)',[('u',1.),('v',3.),('v',3.),('v',3.),('w',8.)])
            edge={'from_table':'plant.sqlite::samples','from_column':'owner_ref','to_table':'plant.sqlite::units','to_column':'unit_ref'}
            catalog={'tables':{'plant.sqlite::units':{'columns':['unit_ref','observed_date','target_date']},'plant.sqlite::samples':{'columns':['owner_ref','reading_value']}},'relationships':[edge]}
            p={'population_table':'plant.sqlite::units','observations_table':'plant.sqlite::samples','entity_key':'unit_ref','observation_key':'owner_ref','measurement':{'name':'Mean reading','expression':{'column':'reading_value'},'unit':'units'},'comparison':{'column':'observed_date','value_column':'target_date','operator':'>','value_type':'date','date_part':'date'},'matched_label':'Above target','unmatched_label':'At or below target'}
            plan={'intent':'SIMPLE','analysis_plan':{'source':{'tables':['plant.sqlite::units']},'outputs':[{'id':'held_out','kind':'entity_comparison','parameters':p}]}}
            engine=create_engine('sqlite://');Base.metadata.create_all(engine)
            with Session(engine) as db,patch.object(settings,'DATASETS_DIR',root),patch('app.api.v1.chat.MetadataService.get_profile',return_value={'columns':catalog['tables']['plant.sqlite::units']['columns']}),patch('app.services.metadata_service.MetadataService.get_catalog_index',return_value=catalog),patch('app.llm.client.OllamaClient.call_model',return_value=json.dumps(plan)),patch('app.llm.agent.Agent.run',side_effect=AssertionError('No fallback')):
                db.add(DBProject(id='plant',name='Plant'));db.commit()
                result,failed=process_chat_message(ChatRequest(project_id='plant',dataset_id='plant.sqlite::units',message='Compare observed_date > target_date using calendar dates. Average reading_value within each unit_ref first, then weight every unit equally.'),db,lambda stage:None)
                self.assertFalse(failed,result['content']);self.assertEqual(result['results']['data'][0]['Mean reading'],2.)
                self.assertEqual(result['analysis_plan']['source'],{'tables':['plant.sqlite::units','plant.sqlite::samples'],'join_keys':[edge]})
            with sqlite3.connect(path) as source:
                expected=source.execute('WITH m AS (SELECT owner_ref,AVG(reading_value) AS value FROM samples GROUP BY owner_ref) SELECT AVG(value) FROM units LEFT JOIN m ON unit_ref=owner_ref WHERE date(observed_date)>date(target_date)').fetchone()[0]
            self.assertEqual(result['results']['data'][0]['Mean reading'],expected)
            engine.dispose()
