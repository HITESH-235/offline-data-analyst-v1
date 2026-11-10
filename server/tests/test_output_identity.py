"""System output bindings; exact failure with an immutable stored baseline."""
import copy,json,sqlite3,unittest
from pathlib import Path
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.analysis.operations import validate_plan
from app.services.output_identity import resolve_outputs,OutputIdentityError
from app.services.specification_context import validate_followup
from app.services.analysis_context import load_context
from app.api.v1.chat import process_chat_message
from app.api.v1.projects import list_saved_analyses
from app.models.chat import ChatRequest,DBChatHistory
from app.models.project import DBProject
from app.storage.sqlite.session import Base
from app.services.dataset_manager import DatasetManager
from app.core.config import settings
FIX=json.loads((Path(__file__).parent/'fixtures/output_identity_failure.json').read_text())
BASE=FIX['baseline']['analysis_context']['plan'];DRAFT=FIX['diagnostics']['planner_diagnostics'][0]['output'];REF=DRAFT['reference_message_id'];OLD=BASE['outputs'][0]['id']
HISTORY={'recent_successes':[{'message_id':REF,'analysis':{'version':1,'plan':BASE}}]}
ROOT=Path(settings.WORKSPACE_DIR)/'evaluations/output-identity-fix-2026-11-11'

class OutputIdentity(unittest.TestCase):
    def setUp(self):
        for target in ['urllib.request.urlopen','urllib.request.OpenerDirector.open']:
            p=patch(target,side_effect=AssertionError('External calls blocked'));p.start();self.addCleanup(p.stop)
    def test_structural_reference_and_anchored_rename_have_same_identity(self):
        expected=validate_plan(DRAFT,history=HISTORY)
        self.assertEqual(expected['analysis_plan']['outputs'][0]['id'],OLD)
        referenced=copy.deepcopy(DRAFT);out=referenced['analysis_plan']['outputs'][0];out.pop('id');out['reference_output_id']=OLD
        self.assertEqual(validate_plan(referenced,history=HISTORY),expected)
        alias=copy.deepcopy(DRAFT)
        alias['changed_fields']=[p.replace(OLD,DRAFT['analysis_plan']['outputs'][0]['id']) for p in DRAFT['changed_fields']]
        alias['analysis_plan']['outputs'][0]['reference_output_id']=OLD
        self.assertEqual(validate_plan(alias,history=HISTORY),expected)
        standalone=copy.deepcopy(FIX['baseline']['planner_diagnostics'][0]['output']);standalone['analysis_plan']['outputs'][0].pop('id')
        generated=validate_plan(standalone)['analysis_plan']['outputs'][0]['id'];self.assertTrue(generated.startswith('output_'));self.assertNotIn('2025',generated)
    def test_grouping_label_method_and_presentation_changes_keep_reference(self):
        for kind,params,field,value in [('correlation',{'columns':['x','y'],'method':'pearson'},'method','spearman'),('aggregation',{'measures':[{'id':'n','column':'value','operation':'sum','label':'Value'}],'group_by':['region']},'group_by',[])]:
            base={'source':{'tables':['fixture.csv']},'outputs':[{'id':'stable','kind':kind,'parameters':params}]}
            draft={'intent':'SIMPLE','context_action':'inherit','reference_message_id':'prior','analysis_plan':copy.deepcopy(base),'changed_fields':[f'outputs.stable.parameters.{field}']}
            draft['analysis_plan']['outputs'][0].update(id='new-name',reference_output_id='stable');draft['analysis_plan']['outputs'][0]['parameters'][field]=value
            history={'recent_successes':[{'message_id':'prior','analysis':{'plan':base}}]};r=validate_plan(draft,history=history)
            validate_followup(r['analysis_plan'],history,'prior',r['changed_fields']);self.assertEqual(r['analysis_plan']['outputs'][0]['id'],'stable')
        d=copy.deepcopy(DRAFT);d['analysis_plan']['outputs'][0]['reference_output_id']=OLD;d['analysis_plan']['outputs'][0]['parameters']['matched_label']='Late';d['analysis_plan']['presentation']['table_in_chat']=True
        d['changed_fields'] += [f'outputs.{OLD}.parameters.matched_label','presentation.table_in_chat']
        r=validate_plan(d,history=HISTORY);validate_followup(r['analysis_plan'],HISTORY,REF,r['changed_fields'])
    def test_multiple_crossed_missing_and_ambiguous_bindings(self):
        base=copy.deepcopy(BASE);other=copy.deepcopy(base['outputs'][0]);other['id']='other';base['outputs'].append(other)
        history={'recent_successes':[{'message_id':REF,'analysis':{'plan':base}}]}
        draft=copy.deepcopy(DRAFT);second=copy.deepcopy(draft['analysis_plan']['outputs'][0]);second['id']='alias-b';draft['analysis_plan']['outputs'].append(second)
        with self.assertRaises(OutputIdentityError):resolve_outputs(draft,history)
        draft['analysis_plan']['outputs'][0]['reference_output_id']=OLD;second['reference_output_id']='other'
        r=resolve_outputs(draft,history);self.assertEqual([o['id'] for o in r['analysis_plan']['outputs']],[OLD,'other'])
        bad=copy.deepcopy(draft);bad['analysis_plan']['outputs'][0]['id']='other'
        with self.assertRaises(OutputIdentityError):resolve_outputs(bad,history)
        bad=copy.deepcopy(draft);bad['analysis_plan']['outputs'][1]['reference_output_id']=OLD
        with self.assertRaises(OutputIdentityError):resolve_outputs(bad,history)
        bad=copy.deepcopy(draft);bad['analysis_plan']['outputs'].pop()
        with self.assertRaises(OutputIdentityError):resolve_outputs(bad,history)
        with self.assertRaises(OutputIdentityError):resolve_outputs(draft,{'recent_successes':[]})
    def test_identity_resolution_never_authorizes_a_calculation_change(self):
        d=copy.deepcopy(DRAFT);d['analysis_plan']['outputs'][0]['parameters']['operator']='>='
        r=validate_plan(d,history=HISTORY)
        with self.assertRaises(ValueError):validate_followup(r['analysis_plan'],HISTORY,REF,r['changed_fields'])
    def test_exact_capture_sqlite_context_reopen_and_next_followup(self):
        engine=create_engine('sqlite://');Base.metadata.create_all(engine)
        with Session(engine) as db:
            db.add(DBProject(id='identity',name='Identity'));db.add(DBChatHistory(id=REF,project_id='identity',role='assistant',type='table',content='Persisted baseline.',metadata_json=json.dumps(FIX['baseline'])));db.commit()
            def send(draft):
                with patch('app.llm.client.OllamaClient.call_model',return_value=json.dumps(draft)) as model,patch('app.llm.agent.Agent.run',side_effect=AssertionError('No fallback')):
                    r,failed=process_chat_message(ChatRequest(project_id='identity',dataset_id='olist.db::orders',message='Repeat for 2018.'),db,lambda s:None)
                return r,failed,model.call_count
            r,failed,calls=send(DRAFT);self.assertFalse(failed,r['content']);self.assertEqual(calls,1)
            audit=r['results']['comparison_audit'];self.assertEqual((audit['comparable_count'],audit['matched_count'],audit['missing_actual_count'],audit['missing_comparison_count']),(52777,4078,6,0));self.assertAlmostEqual(audit['percentage'],7.726850711484169,places=12)
            with sqlite3.connect(Path(DatasetManager.get_dataset(None,'olist.db::orders').filepath).resolve().as_uri()+'?mode=ro',uri=True) as source:
                oracle=source.execute("SELECT COUNT(*),SUM(date(order_delivered_customer_date)>date(order_estimated_delivery_date)) FROM orders WHERE order_status='delivered' AND strftime('%Y',order_purchase_timestamp)='2018' AND order_delivered_customer_date IS NOT NULL AND order_estimated_delivery_date IS NOT NULL").fetchone()
            self.assertEqual(oracle,(52777,4078));self.assertEqual(r['analysis_package']['charts'],[])
            self.assertEqual(r['analysis_plan']['outputs'][0]['id'],OLD);self.assertEqual(r['analysis_package']['tables'][0]['id'],OLD)
            self.assertEqual(r['analysis_package']['requirements']['outputs'][0]['id'],OLD);self.assertEqual(r['calculation']['steps'][0]['output_id'],OLD)
            db.close();self.assertEqual(list_saved_analyses('identity',db)[0]['analysisPackage'],r['analysis_package']);self.assertEqual(load_context(db,'identity')['recent_successes'][0]['analysis']['plan'],r['analysis_plan'])
            follow={'intent':'SIMPLE','context_action':'inherit','reference_message_id':r['id'],'analysis_plan':copy.deepcopy(r['analysis_plan']),'changed_fields':['presentation.table_in_chat']}
            out=follow['analysis_plan']['outputs'][0];out.pop('id');out['reference_output_id']=OLD;follow['analysis_plan']['presentation']['table_in_chat']=True
            second,failed,calls=send(follow);self.assertFalse(failed,second['content']);self.assertEqual(second['analysis_plan']['outputs'][0]['id'],OLD)
            bad=copy.deepcopy(follow);bad['reference_message_id']='missing'
            rejected,failed,calls=send(bad);self.assertTrue(failed);self.assertEqual(calls,1);self.assertEqual(rejected['analysis_status'],'clarification')
            self.assertEqual(json.loads(db.get(DBChatHistory,REF).metadata_json),FIX['baseline'])
            ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'replay.json').write_text(json.dumps({'live_calls':0,'mocked_calls':1,'sqlite':oracle,'result':r,'subsequent_followup':second},indent=2)+'\n')
        engine.dispose()
