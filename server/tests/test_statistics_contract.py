"""Offline diagnosis vs corrected specification; independent SQLite oracle."""
import copy,json,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.analysis.operations import execute,stamp,output_contract,validate,ChartScope
from app.services.analysis_package import OutputAccumulator,finalize
from app.services.analysis_context import _historical_context
from app.services.dataset_manager import DatasetManager
from app.api.v1.chat import process_chat_message
from app.api.v1.projects import list_saved_analyses
from app.models.chat import ChatRequest
from app.models.project import DBProject
from app.storage.sqlite.session import Base
from app.core.config import settings
ROOT=Path(settings.WORKSPACE_DIR)/'evaluations/statistics-contract-fix-2026-11-11'
SELECTION=['count','mean','median','min','max']

class StatisticsContract(unittest.TestCase):
    def setUp(self):
        for target in ['urllib.request.urlopen','urllib.request.OpenerDirector.open']:
            p=patch(target,side_effect=AssertionError('No live calls'));p.start();self.addCleanup(p.stop)
    def publish(self,p,frame,preference='automatic'):
        plan={'source':{'tables':['fixture']},'outputs':[{'id':'stats','kind':'statistics','parameters':p}],'chart_scope':{'preference':preference}}
        contract=output_contract(plan);r=execute('statistics',p,frame);a=OutputAccumulator();a.record('statistics',p,r,plan['source'],0,'stats',contract)
        return finalize({'analysis_outputs':a.export(),'analysis_plan':plan},'Describe','p','r',contract)
    def test_nonmissing_subsets_empty_and_all_null(self):
        p={'columns':['measurement'],'statistics':SELECTION,'return_table':True}
        for frame,count,mean in [(pd.DataFrame({'measurement':[1.,None,3.,None]}),2,2.),(pd.DataFrame({'measurement':[None,None]}),0,None),(pd.DataFrame({'measurement':pd.Series([],dtype=float)}),0,None)]:
            r=execute('statistics',p,frame);values=r['statistics']['measurement']
            self.assertEqual(set(values),set(SELECTION));self.assertEqual(values['count'],count);self.assertEqual(values['mean'],mean)
            self.assertEqual(r['data'][0]['count'],count)
        r=execute('statistics',{'columns':['measurement'],'statistics':['median'],'return_table':True},pd.DataFrame({'measurement':[1,3,8]}))
        self.assertEqual(r['columns'],['column','median']);self.assertEqual(r['statistics'],{'measurement':{'median':3.}})
    def test_outlier_selection_preserves_iqr_analysis_without_unsolicited_arrays(self):
        frame=pd.DataFrame({'sensor':[0]*8+[100]})
        for selection in [['outliers_count'],['iqr','outliers_count','outliers_percentage','outlier_values']]:
            p={'columns':['sensor'],'statistics':selection,'return_table':True};r=execute('statistics',p,frame)
            self.assertEqual(r['statistics']['sensor']['outliers_count'],1)
            self.assertEqual('outlier_values' in r['statistics']['sensor'],'outlier_values' in selection)
            if 'outlier_values' in selection:self.assertEqual(r['data'][0]['outlier_values'],[100.])
    def test_missing_selected_statistic_cannot_be_certified_by_re_stamping(self):
        p={'columns':['reading'],'statistics':['count','mean'],'return_table':True};r=execute('statistics',p,pd.DataFrame({'reading':[1.,None]}))
        del r['statistics']['reading']['count'];del r['data'][0]['count'];stamp('statistics',p,r)
        with self.assertRaises(ValueError):OutputAccumulator().record('statistics',p,r,{'tables':['fixture']},0)
    def test_chart_preferences_configured_charts_and_tables(self):
        p={'columns':['alpha','beta'],'statistics':['mean'],'return_table':True};frame=pd.DataFrame({'alpha':[1,2],'beta':[3,4]})
        for preference in ['required','automatic','disabled']:
            r=self.publish(p,frame,preference);pack=r['analysis_package']
            self.assertEqual(pack['status'],'complete');self.assertEqual(len(pack['tables']),1)
            self.assertEqual(bool(pack['charts']),preference!='disabled')
            for c in pack['charts']:self.assertEqual((c['specification']['x'],c['specification']['y']),('column','mean'))
            self.assertEqual(json.loads(json.dumps(pack))['chart_scope']['preference'],preference)
        r=self.publish({**p,'statistics':['count','mean']},frame,'required');self.assertEqual(r['analysis_status'],'incomplete')
        self.assertEqual(ChartScope.model_validate({'required':True}).preference,'required')
        with self.assertRaises(ValueError):ChartScope.model_validate({'required':True,'preference':'disabled'})
    def test_historical_statistics_context_adapts_without_record_rewrite(self):
        old={'version':1,'plan':{'source':{'tables':['old.csv']},'outputs':[{'id':'old','kind':'statistics','parameters':{'columns':['reading'],'return_table':True}}]}}
        original=copy.deepcopy(old);loaded=_historical_context(old,[])
        self.assertEqual(old,original);self.assertIn('mean',loaded['plan']['outputs'][0]['parameters']['statistics'])
        with self.assertRaises(ValueError):validate('statistics',{'columns':['reading']})
    def test_captured_plan_diagnosis_and_corrected_plan_sqlite_saved_reopen(self):
        capture=json.loads((Path(settings.WORKSPACE_DIR)/'evaluations/statistics-count-review-2026-11-11/response.json').read_text())['metadata']
        draft=capture['planner_diagnostics'][0]['output'];corrected=copy.deepcopy(draft)
        corrected['analysis_plan']['outputs'][0]['parameters'].update(statistics=SELECTION,unit='cents')
        corrected['analysis_plan']['chart_scope']={'preference':'disabled'}
        engine=create_engine('sqlite://');Base.metadata.create_all(engine)
        with Session(engine) as db:
            db.add(DBProject(id='stats',name='Statistics'));db.commit()
            def send(replies):
                with patch('app.llm.client.OllamaClient.call_model',side_effect=[json.dumps(r) for r in replies]) as model,patch('app.llm.agent.Agent.run',side_effect=AssertionError('No fallback')):
                    r,failed=process_chat_message(ChatRequest(project_id='stats',dataset_id='olist.db::order_items',message=capture['question']),db,lambda s:None)
                return r,failed,model.call_count
            rejected,failed,calls=send([draft,draft]);self.assertTrue(failed);self.assertEqual(calls,2);self.assertNotIn('results',rejected)
            r,failed,calls=send([corrected]);self.assertFalse(failed,r['content']);self.assertEqual(calls,1)
            self.assertEqual(r['results']['columns'],['column',*SELECTION]);self.assertEqual(r['analysis_package']['charts'],[])
            self.assertIn('112,650',r['content']);self.assertIn('median',r['content']);self.assertNotIn('2 of 2',r['content'])
            self.assertNotIn('outlier_values',json.dumps(r['results']))
            oracle={}
            path=Path(DatasetManager.get_dataset(None,'olist.db::order_items').filepath)
            with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as source:
                for column in ['price_cents','freight_value_cents']:
                    n,mean,minimum,maximum=source.execute(f'SELECT COUNT({column}),AVG({column}),MIN({column}),MAX({column}) FROM order_items').fetchone()
                    median=source.execute(f'SELECT AVG(v) FROM (SELECT {column} v FROM order_items WHERE {column} IS NOT NULL ORDER BY {column} LIMIT 2 OFFSET ?)',(n//2-1,)).fetchone()[0]
                    oracle[column]={'count':n,'mean':mean,'median':median,'min':minimum,'max':maximum}
                    for key,value in oracle[column].items():self.assertAlmostEqual(r['results']['statistics'][column][key],value,places=8)
            self.assertEqual([oracle[c]['count'] for c in oracle],[112650,112650])
            saved=list_saved_analyses('stats',db)[0];self.assertEqual(saved['analysisPackage'],r['analysis_package'])
            ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'replay.json').write_text(json.dumps({'live_model_calls':0,'captured_diagnosis':rejected['content'],'corrected_specification_fixture':corrected,'sqlite':oracle,'result':r},indent=2)+'\n')
        engine.dispose()
