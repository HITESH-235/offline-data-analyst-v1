"""Shared typed path contract; captured follow-up and independent SQLite."""
import copy,json,sqlite3,unittest
from pathlib import Path
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.analysis.operations import validate_plan,ContractError
from app.services.change_paths import permissions
from app.services.specification_context import validate_followup
from app.services.analysis_context import load_context
from app.api.v1.chat import process_chat_message
from app.api.v1.projects import list_saved_analyses
from app.models.chat import ChatRequest
from app.models.project import DBProject
from app.storage.sqlite.session import Base
from app.services.dataset_manager import DatasetManager
from app.core.config import settings
FIXTURE=json.loads((Path(__file__).parent/'fixtures/followup_products_capture.json').read_text())
BASE=FIXTURE['baseline']['plan']['analysis_plan'];FOLLOW=FIXTURE['reply'];KEY=BASE['outputs'][0]['id']
ROOT=Path(settings.WORKSPACE_DIR)/'evaluations/followup-change-paths-2026-11-11'

class ChangePaths(unittest.TestCase):
    def setUp(self):
        for target in ['urllib.request.urlopen','urllib.request.OpenerDirector.open']:
            p=patch(target,side_effect=AssertionError('External calls blocked'));p.start();self.addCleanup(p.stop)
        self.history={'recent_successes':[{'message_id':FIXTURE['reference'],'analysis':{'version':1,'plan':BASE}}]}
    def test_precise_sections_optional_limit_and_schema_errors(self):
        after=FOLLOW['analysis_plan']
        for paths in [[f'outputs.{KEY}.parameters.limit','presentation.table_in_chat'],[f'outputs.{KEY}.parameters','presentation'],['limit','presentation.table_in_chat']]:
            validate_followup(after,self.history,FIXTURE['reference'],paths)
        for path in ['presentation.typo','chart_scope.typo',f'outputs.{KEY}.parameters.unknown',f'outputs.{KEY}.parameters.measures.999.column',f'outputs.{KEY}.parameters.measures.-1',f'outputs.{KEY}.parameters.measures.01','outputs.unknown.parameters','outputs',f'outputs.{KEY}.kind',f'outputs.{KEY}.parameters.limit.child','source.join_keys.5.from_column']:
            with self.subTest(path=path),self.assertRaises(ContractError):permissions(after,[path],BASE)
        # An absent optional field is owned by its schema, not by an arbitrary string.
        permissions(after,[f'outputs.{KEY}.parameters.limit'],after)
        validate_followup(BASE,{'recent_successes':[{'message_id':'all','analysis':{'plan':after}}]},'all',['limit','presentation.table_in_chat'])
    def test_scope_presentation_and_calculations_remain_independent(self):
        for section,path,value in [('presentation','presentation.table_in_chat',False),('chart_scope','chart_scope.top_n',10)]:
            after=copy.deepcopy(BASE);after[section][path.split('.')[-1]]=value
            validate_followup(after,self.history,FIXTURE['reference'],[path])
            after['outputs'][0]['parameters']['measures'][0]['operation']='count'
            with self.assertRaises(ContractError):validate_followup(after,self.history,FIXTURE['reference'],[path])
        after=copy.deepcopy(FOLLOW['analysis_plan']);after['chart_scope']['top_n']=10
        with self.assertRaises(ContractError):validate_followup(after,self.history,FIXTURE['reference'],FOLLOW['changed_fields'])
    def test_multiple_outputs_sources_and_precise_filters(self):
        before=copy.deepcopy(BASE);other=copy.deepcopy(before['outputs'][0]);other['id']='other';before['outputs'].append(other)
        after=copy.deepcopy(before);after['outputs'][1]['parameters']['limit']=10
        history={'recent_successes':[{'message_id':'multi','analysis':{'plan':before}}]}
        validate_followup(after,history,'multi',['outputs.other.parameters.limit'])
        with self.assertRaises(ContractError):permissions(after,['limit'],before)
        after['outputs'][0]['parameters']['limit']=4
        with self.assertRaises(ContractError):validate_followup(after,history,'multi',['outputs.other.parameters.limit'])
        # Source permissions do not reach formulas or independently declared sources.
        before=copy.deepcopy(BASE);before['outputs'][0]['source']=copy.deepcopy(before['source']);after=copy.deepcopy(before)
        after['outputs'][0]['source']['join_keys'][0]['from_column']='Changed'
        history={'recent_successes':[{'message_id':'s','analysis':{'plan':before}}]}
        with self.assertRaises(ContractError):validate_followup(after,history,'s',['source'])
        validate_followup(after,history,'s',[f'outputs.{KEY}.source.join_keys.0.from_column'])
        p=copy.deepcopy(BASE);p['outputs'][0]['parameters']['filters']=[{'column':'Quantity','operator':'>','value':0}]
        q=copy.deepcopy(p);q['outputs'][0]['parameters']['filters'][0]['value']=1
        validate_followup(q,{'recent_successes':[{'message_id':'f','analysis':{'plan':p}}]},'f',[f'outputs.{KEY}.parameters.filters.0.value'])
    def test_exact_capture_after_success_sqlite_reopen_and_single_repair(self):
        engine=create_engine('sqlite://');Base.metadata.create_all(engine)
        with Session(engine) as db:
            db.add(DBProject(id='paths',name='Paths'));db.commit()
            def send(question,replies):
                with patch('app.llm.client.OllamaClient.call_model',side_effect=[json.dumps(r) for r in replies]) as model,patch('app.llm.agent.Agent.run',side_effect=AssertionError('No fallback')):
                    r,failed=process_chat_message(ChatRequest(project_id='paths',dataset_id='northwind.db::Products',message=question),db,lambda s:None)
                return r,failed,model.call_count
            with patch('app.api.v1.chat.uuid.uuid4',side_effect=['baseline-user',FIXTURE['reference']]):
                baseline,failed,_=send(FIXTURE['baseline']['question'],[FIXTURE['baseline']['plan']])
            self.assertFalse(failed,baseline['content']);self.assertEqual(len(baseline['results']['data']),5)
            r,failed,calls=send(FIXTURE['question'],[FOLLOW]);self.assertFalse(failed,r['content']);self.assertEqual(calls,1)
            self.assertEqual(len(r['results']['data']),77);self.assertNotIn('| ProductName |',r['content'])
            self.assertEqual(r['analysis_package']['chart_scope']['top_n'],5)
            self.assertEqual(r['analysis_plan']['source'],baseline['analysis_plan']['source'])
            self.assertEqual(r['analysis_plan']['outputs'][0]['parameters']['measures'],baseline['analysis_plan']['outputs'][0]['parameters']['measures'])
            with sqlite3.connect(Path(DatasetManager.get_dataset(None,'northwind.db::Products').filepath).resolve().as_uri()+'?mode=ro',uri=True) as source:
                oracle=source.execute('SELECT p.ProductName,SUM(d.Quantity) FROM Products p JOIN "Order Details" d ON p.ProductID=d.ProductID GROUP BY p.ProductName ORDER BY SUM(d.Quantity) DESC,p.ProductName ASC').fetchall()
            self.assertEqual([(x['ProductName'],x['Total Quantity Sold']) for x in r['results']['data']],oracle)
            self.assertEqual(r['results']['data'][:5],baseline['results']['data'])
            db.close() # Reopen the SQLAlchemy session from persisted data, not identity-map state.
            self.assertEqual(load_context(db,'paths')['recent_successes'][0]['analysis']['plan'],r['analysis_plan'])
            self.assertEqual(list_saved_analyses('paths',db)[0]['analysisPackage'],r['analysis_package'])
            # Return to the original successful reference; a typo is repaired
            # within the original two-call budget, with calculation held fixed.
            bad=copy.deepcopy(FOLLOW);bad['changed_fields'][1]='presentation.table_in_chatt'
            fixed,failed,calls=send(FIXTURE['question'],[bad,FOLLOW]);self.assertFalse(failed,fixed['content']);self.assertEqual(calls,2)
            self.assertEqual([d['accepted'] for d in fixed['planner_diagnostics']],[False,True])
            index_bad=copy.deepcopy(FOLLOW);index_bad['changed_fields'].append(f'outputs.{KEY}.parameters.measures.99.column')
            fail,failed,calls=send(FIXTURE['question'],[index_bad,index_bad]);self.assertTrue(failed);self.assertEqual(calls,2);self.assertNotIn('results',fail)
            ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'replay.json').write_text(json.dumps({'live_calls':0,'exact_captured_response':FOLLOW,'baseline':baseline,'result':r,'sqlite':oracle},indent=2)+'\n')
        engine.dispose()
