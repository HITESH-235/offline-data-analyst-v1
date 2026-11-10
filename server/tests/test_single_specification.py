"""Captured replay and expected-specification evaluation, never live planning."""
import copy,json,sqlite3,unittest
from pathlib import Path
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.analysis.operations import validate_plan,canonical,execute,ContractError,planner_instructions,output_contract
from app.services.specification_context import validate_followup
from app.api.v1.chat import process_chat_message
from app.api.v1.projects import list_saved_analyses
from app.models.chat import ChatRequest
from app.models.project import DBProject
from app.storage.sqlite.session import Base
from app.services.dataset_manager import DatasetManager
from app.services.analysis_context import load_context
from app.core.config import settings
from app.services import planned_analysis
import pandas as pd

ROOT=Path(settings.WORKSPACE_DIR)/'evaluations/single-specification-2026-11-10'
QUICK=Path(settings.WORKSPACE_DIR)/'evaluations/quick-review-2026-11-10'

def same_spec(expected,actual):
    """Offline semantic oracle: expected specification is authored independently."""
    try:e=validate_plan(expected)['analysis_plan'];a=validate_plan(actual)['analysis_plan']
    except ValueError:return False
    if e['source']!=a['source'] or len(e['outputs'])!=len(a['outputs']):return False
    return all(x['kind']==y['kind'] and canonical(x['kind'],x['parameters'])==canonical(y['kind'],y['parameters']) for x,y in zip(e['outputs'],a['outputs']))

class SingleSpecification(unittest.TestCase):
    def setUp(self):
        for target in ['urllib.request.urlopen','urllib.request.OpenerDirector.open']:
            blocker=patch(target,side_effect=AssertionError('External calls blocked'));blocker.start();self.addCleanup(blocker.stop)
        self.engine=create_engine('sqlite://');Base.metadata.create_all(self.engine);self.db=Session(self.engine)
        self.db.add(DBProject(id='single',name='Single specification'));self.db.commit()
    def tearDown(self):self.db.close();self.engine.dispose()
    def send(self,question,dataset,replies):
        with patch('app.llm.client.OllamaClient.call_model',side_effect=[json.dumps(p) for p in replies]) as model,patch.object(planned_analysis,'run',wraps=planned_analysis.run) as coordinator,patch('app.llm.agent.Agent.run',side_effect=AssertionError('No alternate route')):
            r,failed=process_chat_message(ChatRequest(project_id='single',dataset_id=dataset,message=question),self.db,lambda s:None)
        self.assertLessEqual(model.call_count,2)
        if not failed:
            self.assertEqual(coordinator.call_count,1);self.assertEqual(r['analysis_status'],'complete',r['content'])
            self.assertEqual(list_saved_analyses('single',self.db)[0]['analysisPackage'],r['analysis_package'])
        return r,failed,model.call_count
    def test_actual_persisted_payment_audit_bounded_repair_and_sqlite(self):
        capture=json.loads((Path(__file__).parent/'fixtures/payment_audit_failure.json').read_text())['metadata']
        replies=[d['output'] for d in capture['planner_diagnostics']]
        r,failed,calls=self.send(capture['question'],'olist.db::order_financials',replies)
        self.assertFalse(failed,r['content']);self.assertEqual(calls,2)
        expected={name:value for name,value in [('total_orders',99441),('orders_with_payments',99440),('orders_without_payments',1)]}
        actual={t['id']:next(iter(t['result']['data'][0].values())) for t in r['analysis_package']['tables']}
        self.assertEqual(actual,expected)
        self.assertTrue(r['scalar_answer']);self.assertFalse(r['analysis_package']['presentation']['has_detail'])
        self.assertNotIn('Open result',r['content'])
        with sqlite3.connect(Path(DatasetManager.get_dataset(None,'olist.db::order_financials').filepath).resolve().as_uri()+'?mode=ro',uri=True) as db:
            self.assertEqual(db.execute('SELECT COUNT(*),SUM(has_payments=1),SUM(has_payments=0) FROM order_financials').fetchone(),(99441,99440,1))
        for out in r['analysis_plan']['outputs']:
            self.assertIn('measures',out['parameters']);self.assertNotIn('aggregations',out['parameters']);self.assertNotIn('output_names',out['parameters'])
        ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'payment-audit-replay.json').write_text(json.dumps({'category':'A captured replay; C independent SQLite','live_calls':0,'result':r},indent=2)+'\n')
    def test_captured_calculations_match_independent_sqlite(self):
        evidence=[]
        for key in ['G01','Q02','Q03','Q07','Q08']:
            capture=json.loads((QUICK/(key+'.json')).read_text());case=capture['case']
            r,failed,_=self.send(case['question'],case['dataset'],[a['output'] for a in capture['result']['planner_diagnostics']])
            self.assertFalse(failed,(key,r['content']))
            with sqlite3.connect(Path(DatasetManager.get_dataset(None,case['dataset']).filepath).resolve().as_uri()+'?mode=ro',uri=True) as db:expected=db.execute(case['sql']).fetchall()
            rows=r['results']['data'];self.assertEqual(len(rows),len(expected))
            if key=='G01':
                audit={v['customer_state']:v for v in r['results']['comparison_audit']['groups']}
                for state,n,late,rate in expected:
                    self.assertEqual((audit[state]['comparable_count'],audit[state]['matched_count']),(n,late));self.assertAlmostEqual(audit[state]['percentage'],rate,places=8)
                self.assertEqual(r['results']['comparison_audit']['missing_actual_count'],8)
            else:
                got={row[r['results']['columns'][0]]:row[r['results']['columns'][1]] for row in rows}
                for row in expected:self.assertAlmostEqual(got[row[0] if key!='Q03' else f'{row[0]}-{row[1]:02d}'],row[-1],places=6)
            evidence.append({'case':key,'rows':len(rows),'sqlite_match':True})
        (ROOT/'captured-calculations.json').write_text(json.dumps(evidence,indent=2)+'\n')
    def test_expected_specs_catch_semantic_errors_without_runtime_english_oracle(self):
        capture=json.loads((QUICK/'Q03.json').read_text());expected=capture['result']['planner_diagnostics'][-1]['output']
        for field,value in [('expression',{'column':'UnitPrice'}),('years',[2022]),('grain','quarter'),('filters',[{'column':'ShipCountry','operator':'==','value':'Brazil'}])]:
            wrong=copy.deepcopy(expected);p=wrong['analysis_plan']['outputs'][0]['parameters'];(p['metric'] if field=='expression' else p)[field]=value
            self.assertFalse(same_spec(expected,wrong))
        # Associativity and multiplication order have provable typed equivalence.
        equivalent=copy.deepcopy(expected);p=equivalent['analysis_plan']['outputs'][0]['parameters'];p['metric']['expression']['args'].reverse()
        self.assertTrue(same_spec(expected,equivalent))
    def test_stable_measure_ownership_and_ambiguous_legacy_references(self):
        p={'measures':[{'id':'orders','column':'ticket_key','operation':'count','label':'Total tickets'}]}
        r=execute('aggregation',p,pd.DataFrame({'ticket_key':['a','b',None]}))
        self.assertEqual(r['data'],[{'Total tickets':2}]);self.assertEqual(r['measure_provenance']['Total tickets']['measure_id'],'orders')
        legacy={'aggregations':{'a':'count','b':'count'},'output_names':{'count':'Count'}}
        from app.analysis.operations import validate
        with self.assertRaises(ValueError):validate('aggregation',legacy)
        with self.assertRaises(ValueError):validate('aggregation',{**p,'aggregations':{'ticket_key':'count'}})
        with self.assertRaises(ValueError):validate('aggregation',{'measures':[{'id':'orders','column':'ticket_key','operation':'median','label':'Median'}]})
    def test_structured_context_preserves_all_undeclared_fields_and_ambiguity(self):
        capture=json.loads((QUICK/'Q03.json').read_text());base=validate_plan(capture['result']['planner_diagnostics'][-1]['output'])['analysis_plan']
        history={'recent_successes':[{'message_id':'verified','analysis':{'version':1,'plan':base}}],'unresolved_request':{'plan':{'source':{'tables':['unrelated']}}}}
        changed=copy.deepcopy(base);out=changed['outputs'][0];out['parameters']['grain']='quarter'
        validate_followup(changed,history,'verified',['grain'])
        out['parameters']['years']=[2022]
        with self.assertRaises(ContractError):validate_followup(changed,history,'verified',['grain'])
        with self.assertRaises(ContractError):validate_followup(base,history,None,[])
        with self.assertRaises(ContractError):validate_followup(base,history,'unresolved',[])
    def test_no_runtime_language_interpreters_or_reviewer_schema(self):
        import app.services.request_requirements as old
        import app.services.analysis_context as context
        self.assertFalse(hasattr(old,'derive'));self.assertFalse(hasattr(context,'grouping_update'));self.assertFalse(hasattr(context,'resolve_request_context'))
        schema=json.loads(planner_instructions().split('Envelope schema:\n')[1]);agg=schema['$defs']['Parameters_aggregation']['properties']
        self.assertIn('measures',agg)
        for name in ['aggregations','output_names','transforms']:self.assertNotIn(name,agg)
    def test_held_out_word_forms_use_expected_typed_formula_not_runtime_parsing(self):
        # Constructed planning fixtures test the contract; they do not demonstrate
        # that a live model understands these wordings.
        from app.analysis.operations import formula_identity
        expression={'op':'multiply','args':[{'column':'UnitFee'},{'column':'Units'},{'op':'subtract','args':[{'value':1},{'column':'Rebate'}]}]}
        frame=pd.DataFrame({'BookedOn':['2024-01-01','2024-02-01'],'UnitFee':[100.,30.],'Units':[2,3],'Rebate':[.25,.1]})
        p={'date_column':'BookedOn','years':[2024],'grain':'month','metric':{'name':'Net Fees','aggregation':'sum','expression':expression}}
        wordings=['SUM(UnitFee × Units × (1 − Rebate))','SUM(UnitFee * Units * (1 - Rebate))','sum of UnitFee times Units times (one minus Rebate)','SUM(((UnitFee * Units) * ((1 - Rebate))))']
        for wording in wordings:
            with self.subTest(constructed_wording=wording):
                result=execute('calendar_aggregate',p,frame)
                with sqlite3.connect(':memory:') as db:
                    frame.to_sql('observations',db,index=False)
                    value=db.execute('SELECT SUM(UnitFee*Units*(1-Rebate)) FROM observations').fetchone()[0]
                self.assertAlmostEqual(sum(row['Net Fees'] for row in result['data']),value)
        self.assertNotEqual(formula_identity(expression),formula_identity({'column':'UnitFee'}))
    def test_standalone_wording_transitions_do_not_reinterpret_or_inherit(self):
        fixture=json.loads((Path(__file__).parent/'fixtures/entity_comparison_plan.json').read_text())
        first,failed,_=self.send(fixture['question'],'olist.db::orders',[fixture['plan']]);self.assertFalse(failed,first['content'])
        self.db.close();self.db=Session(self.engine)
        capture=json.loads((Path(__file__).parent/'fixtures/standalone_financial_context_failure.json').read_text())['metadata']
        draft=capture['planner_diagnostics'][0]['output']
        for suffix in ['Do not inherit previous filters.','Ignore earlier analyses.','This is a new standalone request.','Never reuse the prior analysis.']:
            q=capture['question'].split('Use one financial record')[0]+suffix
            result,failed,calls=self.send(q,'olist.db::orders',[draft]);self.assertFalse(failed,result['content']);self.assertEqual(calls,1)
            self.assertEqual(len(result['results']['data']),27)
            self.assertAlmostEqual(sum(row['Paid Amount (BRL)'] for row in result['results']['data']),8699763.05,places=6)
            self.assertIsNone(result['analysis_package']['request_requirements'])
    def test_entity_year_paths_reject_undeclared_population_and_formula_changes(self):
        fixture=json.loads((Path(__file__).parent/'fixtures/entity_comparison_plan.json').read_text())
        baseline=validate_plan(fixture['plan'])['analysis_plan'];history={'recent_successes':[{'message_id':'review','analysis':{'version':1,'plan':baseline}}]}
        reordered=copy.deepcopy(baseline);reordered['outputs'][0]['parameters']['filters'].reverse()
        validate_followup(reordered,history,'review',[]) # Identical AND predicates have equivalent order.
        out=baseline['outputs'][0];follow=copy.deepcopy(baseline);p=follow['outputs'][0]['parameters']
        p['filters'][1]['value']='2017-01-01';p['filters'][2]['value']='2018-01-01'
        paths=[f"outputs.{out['id']}.parameters.filters.{i}.value" for i in (1,2)]
        validate_followup(follow,history,'review',paths)
        p['filters'][0]['value']='canceled'
        with self.assertRaises(ContractError):validate_followup(follow,history,'review',paths)
        p['filters'][0]['value']='delivered';p['measurement']['expression']={'value':1}
        with self.assertRaises(ContractError):validate_followup(follow,history,'review',paths)
    def test_ambiguous_reference_returns_clarification_without_execution(self):
        capture=json.loads((QUICK/'Q03.json').read_text());draft=copy.deepcopy(capture['result']['planner_diagnostics'][-1]['output'])
        draft.update(context_action='inherit',reference_message_id=None)
        r,failed,calls=self.send('Compare that with the other one.','northwind.db::Orders',[draft])
        self.assertTrue(failed);self.assertEqual(calls,1);self.assertEqual(r['analysis_status'],'clarification');self.assertNotIn('results',r)
    def test_old_saved_aggregate_is_loaded_canonically_without_rewriting_record(self):
        from app.services.analysis_context import _historical_context
        old={'version':1,'plan':{'source':{'tables':['orders.csv']},'outputs':[{'id':'count','kind':'aggregation','parameters':{'aggregations':{'ticket_key':'count'},'output_names':{'count':'Tickets'}}}]}}
        original=copy.deepcopy(old);loaded=_historical_context(old,[])
        self.assertEqual(old,original);self.assertIn('measures',loaded['plan']['outputs'][0]['parameters'])
        self.assertEqual(loaded['plan']['outputs'][0]['parameters']['measures'][0]['column'],'ticket_key')
        spaced={'aggregations':{'ticket key':'count'},'output_names':{'count':'Tickets'},'sort_by':'ticket key'}
        result=execute('aggregation',spaced,pd.DataFrame({'ticket key':['a','b']}))
        self.assertEqual(result['data'],[{'Tickets':2}])
        self.assertTrue(result['measure_provenance']['Tickets']['measure_id'].startswith('measure_'))
    def test_repair_cannot_reduce_a_new_stable_measure(self):
        from app.analysis.operations import guard_repair
        original={'intent':'SIMPLE','analysis_plan':{'source':{'tables':['tickets.csv']},'outputs':[{'id':'count','kind':'aggregation','parameters':{'ascending':None,'measures':[{'id':'tickets','column':'ticket_key','operation':'count_distinct','label':'Tickets'}]}}]}}
        fixed=copy.deepcopy(original);fixed['analysis_plan']['outputs'][0]['parameters'].pop('ascending')
        guard_repair(original,fixed)
        fixed['analysis_plan']['outputs'][0]['parameters']['measures'][0]['operation']='count'
        with self.assertRaises(ValueError):guard_repair(original,fixed)
