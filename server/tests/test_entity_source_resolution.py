"""Replay the exact live omission; reject contradictions before calculation."""
import copy
import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
import test_entity_comparison as staged
from app.analysis.operations import validate_plan,ContractError
from app.analysis.entity_comparison import resolve_source
from app.api.v1.projects import list_saved_analyses
from app.models.project import DBProject
from app.services.analysis_context import load_context
from app.services.dataset_manager import DatasetManager
from app.services.metadata_service import MetadataService
from app.llm.planner import QueryPlanner

CAPTURE=json.loads((Path(__file__).parent/'fixtures/entity_comparison_source_failure.json').read_text())
DRAFT=CAPTURE['metadata']['planner_diagnostics'][0]['output']
ROOT=Path('/app/workspace/evaluations/single-specification-2026-11-10')

class EntitySourceResolution(staged.OfflineTest):
    def setUp(self):
        super().setUp()
        self.engine=create_engine('sqlite://');staged.Base.metadata.create_all(self.engine);self.db=Session(self.engine)
        self.db.add(DBProject(id='staged',name='Source resolution'));self.db.commit()
    def tearDown(self):self.db.close();self.engine.dispose()
    send=staged.EntityComparisonPipeline.send

    def test_exact_capture_sqlite_publication_context_and_reopen(self):
        r,failed=self.send(DRAFT,CAPTURE['metadata']['question']);self.assertFalse(failed,r['content'])
        audit=r['results']['entity_audit']
        with sqlite3.connect(Path(DatasetManager.get_dataset(None,'olist.db::orders').filepath).resolve().as_uri()+'?mode=ro',uri=True) as db:
            db.row_factory=sqlite3.Row;oracle=[dict(row) for row in db.execute(staged.ORACLE)]
        want={v['classification']:v for v in oracle}
        for group in audit['groups']:
            expected=want[group['classification']]
            self.assertEqual((group['comparable_count'],group['contributing_count'],group['missing_record_count'],group['unusable_measurement_count']),
                             (expected['comparable'],expected['contributing'],expected['missing_records'],expected['unusable']))
            self.assertAlmostEqual(group['mean'],expected['mean_score'],places=12)
        self.assertEqual((audit['missing_actual_count'],audit['missing_comparison_count']),(6,0))
        source=r['analysis_plan']['source'];self.assertEqual(source,staged.PLAN['analysis_plan']['source'])
        p=r['analysis_plan']['outputs'][0]['parameters'];self.assertEqual(p['filters'],DRAFT['analysis_plan']['outputs'][0]['parameters']['filters'])
        self.assertEqual(p['filters'][-1]['operator'],'<=');self.assertEqual(p['filters'][-1]['value'],'2018-12-31')
        package=r['analysis_package'];table=package['tables'][0]
        self.assertEqual(table['source'],source)
        self.assertEqual(package['requirements']['outputs'][0]['source_tables'],source['tables'])
        self.assertEqual(package['requirements']['outputs'][0]['join_keys'],source['join_keys'])
        self.assertEqual(r['calculation']['steps'][0]['tables'],source['tables'])
        self.db.close();self.db=Session(self.engine)
        self.assertEqual(load_context(self.db,'staged')['recent_successes'][0]['analysis']['plan'],r['analysis_plan'])
        self.assertEqual(next(s for s in list_saved_analyses('staged',self.db) if s['id']==r['id'])['analysisPackage'],package)
        follow=copy.deepcopy(DRAFT);follow.update(context_action='inherit',reference_message_id=r['id'],changed_fields=[])
        again,failed=self.send(follow,'Repeat that same comparison.');self.assertFalse(failed,again['content']);self.assertEqual(again['results']['data'],r['results']['data'])
        ROOT.mkdir(parents=True,exist_ok=True)
        (ROOT/'entity-source-replay.json').write_text(json.dumps({'live_model_calls':0,'question':CAPTURE['metadata']['question'],'captured_fixture_sha256':hashlib.sha256(json.dumps(CAPTURE,sort_keys=True).encode()).hexdigest(),'oracle':oracle,'result':r},indent=2)+'\n')

    def test_omitted_either_source_edge_direction_and_idempotence(self):
        expected=staged.PLAN['analysis_plan']['source']
        for names in [[expected['tables'][0]],[expected['tables'][1]],expected['tables']]:
            for edges in [[],expected['join_keys'],[{'from_table':expected['tables'][0],'from_column':'order_id','to_table':expected['tables'][1],'to_column':'order_id'}]]:
                with self.subTest(names=names,edges=edges):
                    draft=copy.deepcopy(DRAFT);draft['analysis_plan']['source']={'tables':names,'join_keys':edges}
                    resolved=validate_plan(draft);self.assertEqual(resolved['analysis_plan']['source'],expected)
                    self.assertEqual(validate_plan(resolved),resolved)

    def test_conflicting_sources_keys_edges_database_and_extra_tables(self):
        cases=[]
        for source in [
            {'tables':['olist.db::orders','olist.db::customers']},
            {'tables':['olist.db::orders','olist.db::order_reviews','olist.db::order_items']},
            {'tables':['olist.db::orders'],'database':'other.db'},
            {'tables':['olist.db::orders','olist.db::orders']},
            {'tables':['olist.db::orders'],'join_keys':[{'from_table':'olist.db::order_reviews','from_column':'review_id','to_table':'olist.db::orders','to_column':'order_id'}]},
        ]:
            draft=copy.deepcopy(DRAFT);draft['analysis_plan']['source']=source;cases.append(draft)
        for key,value in [('observation_key','review_id'),('entity_key','customer_id'),('observations_table','northwind.db::Orders')]:
            draft=copy.deepcopy(DRAFT);draft['analysis_plan']['outputs'][0]['parameters'][key]=value;cases.append(draft)
        for draft in cases:
            with self.subTest(source=draft['analysis_plan']['source']),self.assertRaises(ContractError):validate_plan(draft)

    def test_mixed_outputs_keep_own_sources_and_publication(self):
        draft=copy.deepcopy(DRAFT)
        draft['analysis_plan']['outputs'].append({'id':'population_count','kind':'aggregation','parameters':{'aggregations':{'order_id':'count'},'filters':copy.deepcopy(staged.PARAMS['filters'])}})
        resolved=validate_plan(draft)['analysis_plan']
        self.assertEqual(resolved['source']['tables'],['olist.db::orders'])
        self.assertEqual(resolved['outputs'][0]['source'],staged.PLAN['analysis_plan']['source'])
        self.assertNotIn('source',resolved['outputs'][1])
        r,failed=self.send(draft);self.assertFalse(failed,r['content'])
        tables={t['id']:t for t in r['analysis_package']['tables']}
        self.assertEqual(tables['requested_entity_comparison']['source'],staged.PLAN['analysis_plan']['source'])
        self.assertEqual(tables['population_count']['source']['tables'],['olist.db::orders'])
        # An explicit unrelated output source remains independent of the default.
        draft['analysis_plan']['outputs'][1]['source']={'tables':['olist.db::customers']}
        self.assertEqual(validate_plan(draft)['analysis_plan']['outputs'][1]['source']['tables'],['olist.db::customers'])

    def test_actual_fk_required_even_with_catalog_claim_and_no_missing_source_guess(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'held.sqlite'
            with sqlite3.connect(path) as db:db.executescript('CREATE TABLE entities(entity_code TEXT PRIMARY KEY, actual REAL, expected REAL); CREATE TABLE measures(owner_code TEXT, reading REAL);')
            p={'population_table':'held.sqlite::entities','observations_table':'held.sqlite::measures','entity_key':'entity_code','observation_key':'owner_code','measurement':{'name':'Reading','expression':{'column':'reading'}},'comparison':{'column':'actual','value_column':'expected','operator':'>','value_type':'number'}}
            edge={'from_table':p['observations_table'],'from_column':'owner_code','to_table':p['population_table'],'to_column':'entity_code'}
            catalog={'tables':{p['population_table']:{'columns':['entity_code','actual','expected']},p['observations_table']:{'columns':['owner_code','reading']}},'relationships':[edge]}
            with patch.object(staged.settings,'DATASETS_DIR',root):
                with self.assertRaisesRegex(ValueError,'single-column foreign key'):resolve_source(p,{'tables':[p['population_table']]},catalog)
                catalog['relationships']=[]
                with self.assertRaisesRegex(ValueError,'missing sources cannot be resolved'):resolve_source(p,{'tables':[p['population_table']]},catalog)

    def test_existing_repair_is_bounded_and_failure_has_one_actionable_reason(self):
        bad=copy.deepcopy(DRAFT);bad['analysis_plan']['source']['tables'].append('olist.db::customers')
        with patch('app.llm.client.OllamaClient.call_model',return_value=json.dumps(bad)) as model,patch('app.services.planned_analysis.run',side_effect=AssertionError('No calculation before validation')):
            r,failed=staged.process_chat_message(staged.ChatRequest(project_id='staged',dataset_id='olist.db::orders',message=staged.QUESTION),self.db,lambda s:None)
        self.assertTrue(failed);self.assertEqual(model.call_count,2)
        self.assertIn('extra source tables',r['content']);self.assertNotIn('Python',r['content']);self.assertNotIn('Execution stopped',r['content'])
        self.assertEqual(len(r['analysis_package']['incomplete_reasons']),1)
        self.assertEqual(len(r['planner_diagnostics']),2);self.assertNotIn('results',r)
