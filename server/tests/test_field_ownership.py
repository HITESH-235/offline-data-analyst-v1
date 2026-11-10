"""Typed alias ownership, indexed changes, exact captured baseline and SQL oracle."""
import copy,json,sqlite3,unittest
from pathlib import Path
from unittest.mock import patch
from pydantic import Field
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.analysis.operations import validate,validate_plan,Typed,ContractError
from app.services.change_paths import permissions,_valid
from app.services.specification_context import validate_followup
from app.services.analysis_context import load_context
from app.api.v1.chat import process_chat_message
from app.api.v1.projects import list_saved_analyses
from app.models.chat import ChatRequest,DBChatHistory
from app.models.project import DBProject
from app.storage.sqlite.session import Base
from app.services.dataset_manager import DatasetManager
from app.core.config import settings
FIXTURE=json.loads((Path(__file__).parent/'fixtures/comparison_year_paths.json').read_text())
BASE=FIXTURE['baseline']['analysis_context']['plan']
DRAFTS=[d['output'] for d in FIXTURE['response']['metadata']['planner_diagnostics']]
REF=DRAFTS[0]['reference_message_id'];KEY=BASE['outputs'][0]['id']
ROOT=Path(settings.WORKSPACE_DIR)/'evaluations/comparison-field-ownership-fix-2026-11-11'

def history(plan=BASE):return {'recent_successes':[{'message_id':REF,'analysis':{'version':1,'plan':plan}}]}

class FieldOwnership(unittest.TestCase):
    def setUp(self):
        for target in ['urllib.request.urlopen','urllib.request.OpenerDirector.open']:
            p=patch(target,side_effect=AssertionError('No external calls'));p.start();self.addCleanup(p.stop)
    def test_parameter_and_path_aliases_have_one_canonical_owner(self):
        draft=DRAFTS[0];canonical=validate_plan(draft)
        self.assertTrue(all('.eligibility_filters.' in p for p in canonical['changed_fields']))
        validate_followup(canonical['analysis_plan'],history(),REF,canonical['changed_fields'])
        alias=copy.deepcopy(draft);p=alias['analysis_plan']['outputs'][0]['parameters'];p['filters']=p.pop('eligibility_filters')
        self.assertEqual(validate_plan(alias),canonical)
        self.assertEqual(permissions(alias['analysis_plan'],draft['changed_fields'],BASE),canonical['changed_fields'])
        collision=copy.deepcopy(p);collision['eligibility_filters']=collision['filters']
        with self.assertRaises(ValueError):validate('comparison_summary',collision)
        aggregate={'measures':[{'id':'n','column':'id','operation':'count','label':'Count'}],'filters':[]}
        self.assertIn('filters',validate('aggregation',aggregate)) if aggregate['filters'] else self.assertNotIn('eligibility_filters',validate('aggregation',aggregate))
        with self.assertRaises(ContractError):permissions({'source':BASE['source'],'outputs':[{'id':'agg','kind':'aggregation','parameters':aggregate}]},['outputs.agg.parameters.eligibility_filters'])
    def test_metadata_collisions_are_rejected_for_both_parameters_and_paths(self):
        class Ambiguous(Typed):
            left:int=Field(json_schema_extra={'input_aliases':['shared']})
            right:int=Field(json_schema_extra={'input_aliases':['shared']})
        with self.assertRaises(ValueError):Ambiguous.model_validate({'shared':1,'left':2,'right':3})
        with self.assertRaises(ContractError):_valid(Ambiguous,['shared'],[{'left':1,'right':2}],True,'$.changed_fields',['parameters'])
    def test_reordered_predicates_and_undeclared_semantic_changes(self):
        canonical=validate_plan(DRAFTS[0]);after=copy.deepcopy(canonical['analysis_plan'])
        after['outputs'][0]['parameters']['eligibility_filters'].reverse()
        validate_followup(after,history(),REF,DRAFTS[0]['changed_fields'])
        for change in ['operator','population','source','chart','presentation']:
            wrong=copy.deepcopy(after);p=wrong['outputs'][0]['parameters']
            if change=='operator':p['operator']='>='
            elif change=='population':p['eligibility_filters'][-1]['value']='canceled'
            elif change=='source':wrong['source']['tables']=['olist.db::customers']
            elif change=='chart':wrong['chart_scope']['preference']='automatic'
            else:wrong['presentation']['table_in_chat']=True
            with self.subTest(change=change),self.assertRaises(ContractError):validate_followup(wrong,history(),REF,DRAFTS[0]['changed_fields'])
        bad=copy.deepcopy(canonical);bad['changed_fields']=[f'outputs.{KEY}.parameters.filters.99.value']
        with self.assertRaisesRegex(ContractError,'eligibility_filters.99.value'):validate_followup(bad['analysis_plan'],history(),REF,bad['changed_fields'])
        with self.assertRaises(ContractError):permissions(after,[f'outputs.{KEY}.parameters.filters.-1.value'],BASE)
    def test_ambiguous_reordered_indices_require_whole_collection(self):
        before=copy.deepcopy(BASE);filters=before['outputs'][0]['parameters']['eligibility_filters'];filters[2]=copy.deepcopy(filters[1]);filters[2]['value']='2025-06-01'
        after=copy.deepcopy(before);after['outputs'][0]['parameters']['eligibility_filters'][1]['value']='2018-01-01';after['outputs'][0]['parameters']['eligibility_filters'][2]['value']='2018-06-01'
        with self.assertRaisesRegex(ContractError,'ambiguous predicate indices'):validate_followup(after,history(before),REF,[f'outputs.{KEY}.parameters.filters.1.value',f'outputs.{KEY}.parameters.filters.2.value'])
        validate_followup(after,history(before),REF,[f'outputs.{KEY}.parameters.filters'])
    def test_multiple_outputs_keep_local_ownership(self):
        before=copy.deepcopy(BASE);other=copy.deepcopy(before['outputs'][0]);other['id']='second';before['outputs'].append(other)
        after=copy.deepcopy(before);after['outputs'][1]['parameters']['eligibility_filters'][1]['value']='2018-01-01'
        validate_followup(after,history(before),REF,['outputs.second.parameters.filters.1.value'])
        with self.assertRaises(ContractError):permissions(after,['filters.1.value'],before)
        after['outputs'][0]['parameters']['operator']='>='
        with self.assertRaises(ContractError):validate_followup(after,history(before),REF,['outputs.second.parameters.filters.1.value'])
    def test_exact_captured_drafts_with_persisted_empty_baseline_and_sqlite(self):
        engine=create_engine('sqlite://');Base.metadata.create_all(engine)
        with Session(engine) as db:
            db.add(DBProject(id='ownership',name='Ownership'))
            baseline=FIXTURE['baseline'];db.add(DBChatHistory(id=REF,project_id='ownership',role='assistant',content='Persisted empty-population baseline.',type='table',metadata_json=json.dumps(baseline)));db.commit()
            self.assertEqual(load_context(db,'ownership')['recent_successes'][0]['analysis']['plan'],BASE)
            self.assertEqual(baseline['results']['comparison_audit']['comparable_count'],0)
            for draft in DRAFTS:
                with patch('app.llm.client.OllamaClient.call_model',return_value=json.dumps(draft)) as model,patch('app.llm.agent.Agent.run',side_effect=AssertionError('No fallback')):
                    r,failed=process_chat_message(ChatRequest(project_id='ownership',dataset_id='olist.db::orders',message=FIXTURE['response']['metadata']['question']),db,lambda s:None)
                self.assertFalse(failed,r['content']);self.assertEqual(model.call_count,1)
                audit=r['results']['comparison_audit']
                self.assertEqual((audit['filtered_count'],audit['comparable_count'],audit['matched_count'],audit['missing_actual_count'],audit['missing_comparison_count']),(52783,52777,4078,6,0))
                self.assertAlmostEqual(audit['percentage'],7.726850711484169,places=12)
                self.assertEqual(r['analysis_package']['charts'],[]);self.assertEqual(r['analysis_package']['chart_scope']['preference'],'disabled')
                self.assertTrue(all('.eligibility_filters.' in p for p in r['planner_diagnostics'][0]['output']['changed_fields']))
            with sqlite3.connect(Path(DatasetManager.get_dataset(None,'olist.db::orders').filepath).resolve().as_uri()+'?mode=ro',uri=True) as source:
                oracle=source.execute("SELECT COUNT(*),SUM(order_delivered_customer_date IS NOT NULL AND order_estimated_delivery_date IS NOT NULL),SUM(date(order_delivered_customer_date)>date(order_estimated_delivery_date)),SUM(order_delivered_customer_date IS NULL),SUM(order_delivered_customer_date IS NOT NULL AND order_estimated_delivery_date IS NULL) FROM orders WHERE order_status='delivered' AND date(order_purchase_timestamp)>='2018-01-01' AND date(order_purchase_timestamp)<'2019-01-01'").fetchone()
            self.assertEqual(oracle,(52783,52777,4078,6,0))
            db.close();self.assertEqual(list_saved_analyses('ownership',db)[0]['analysisPackage'],r['analysis_package'])
            self.assertEqual(load_context(db,'ownership')['recent_successes'][0]['analysis']['plan'],r['analysis_plan'])
            ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'replay.json').write_text(json.dumps({'live_calls':0,'captured_drafts_replayed':2,'calls_per_draft':1,'sqlite':oracle,'result':r},indent=2)+'\n')
        engine.dispose()
