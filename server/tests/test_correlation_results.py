import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.analysis.correlation import compute_correlation, explanation, requested_columns
from app.analysis_engine import AnalysisEngine
from app.api.v1.chat import process_chat_message
from app.api.v1.projects import list_saved_analyses, list_project_messages
from app.core.config import settings
from app.llm.agent import Agent, _execute_tool
from app.models.chat import ChatRequest
from app.models.project import DBProject
from app.storage.sqlite.session import Base

COLUMNS=['UnitPrice','Quantity','Discount']
QUESTION='Show a correlation heatmap of UnitPrice, Quantity, and Discount'


class CorrelationResultTest(unittest.TestCase):
    def setUp(self):
        self.frame=pd.DataFrame({'OrderID':[1,2,3,4,5], 'UnitPrice':[2.,4.,1.,8.,3.],
                                 'Quantity':[1,4,2,5,3], 'Discount':[.1,.2,0.,.15,.1]})

    def result(self):
        return AnalysisEngine.execute_plan(None,'fixture',{'correlation':True,'correlation_columns':COLUMNS},dataframe=self.frame)

    def test_returns_matrix_not_raw_observations(self):
        result=self.result()
        self.assertEqual(result['row_count'],3)
        self.assertEqual(result['source_observation_count'],5)
        self.assertEqual(result['columns'],['Measure',*COLUMNS])
        self.assertNotIn('OrderID',result['columns'])
        expected=self.frame[COLUMNS].corr().to_numpy()
        np.testing.assert_allclose(result['correlation']['matrix'],expected)
        np.testing.assert_allclose([[row[c] for c in COLUMNS] for row in result['data']],expected)
        text=explanation(result)
        for value in expected.flat:self.assertIn(f'{value:.4f}',text)
        self.assertIn('Source observations: 5',text)
        self.assertIn('do not establish statistical independence',text)
        self.assertIn('heatmap in Chart',text)
        json.dumps(result,allow_nan=False)

    def test_null_constants_and_pair_counts_are_honest(self):
        frame=pd.DataFrame({'A':[1.,2.,3.,np.nan], 'B':[4.,4.,4.,4.], 'C':[1.,np.inf,3.,5.]})
        corr=compute_correlation(frame,columns=['C','A','B'])
        self.assertEqual(corr['columns'],['C','A','B'])
        self.assertEqual(corr['pair_observation_counts'][0][1],2)
        self.assertIsNone(corr['matrix'][0][2])
        self.assertIsNone(corr['matrix'][2][2])
        json.dumps(corr,allow_nan=False)

    def test_invalid_methods_columns_and_empty_input_fail(self):
        for columns,method in [(['UnitPrice','Missing'],'pearson'),(['UnitPrice','UnitPrice'],'pearson'),([], 'pearson'),(COLUMNS,'madeup')]:
            with self.assertRaises(ValueError):compute_correlation(self.frame,method,columns)
        with self.assertRaises(ValueError):compute_correlation(self.frame.iloc[:0],columns=COLUMNS)
        with self.assertRaises(ValueError):compute_correlation(self.frame.assign(Text='a'),columns=['Text','Quantity'])
        self.assertEqual(compute_correlation(self.frame)['columns'],COLUMNS)
        self.assertEqual(requested_columns('Discount versus UnitPrice and Quantity',self.frame.columns),['Discount','UnitPrice','Quantity'])

    def test_unsupported_tool_fields_fail_and_spearman_is_supported(self):
        _,result=_execute_tool('correlation',{'columns':COLUMNS,'unknown':True},'fixture',None,{},dataframe=self.frame)
        self.assertIsNone(result)
        _,result=_execute_tool('correlation',{'columns':COLUMNS,'method':'spearman'},'fixture',None,{},dataframe=self.frame)
        self.assertEqual(result['correlation']['method'],'spearman')
        self.assertIn('monotonic rank association',explanation(result))

    def test_false_model_narrative_is_replaced_and_snapshot_reopens(self):
        engine=create_engine('sqlite://')
        Base.metadata.create_all(engine)
        replies=[json.dumps({'action':'tool_call','tool':'correlation','parameters':{'method':'pearson'}}),
                 json.dumps({'action':'final_answer','content':'Heatmaps unavailable. These variables are statistically independent.'})]
        with Session(engine) as db, tempfile.TemporaryDirectory() as directory, patch.object(settings,'WORKSPACE_DIR',directory):
            db.add(DBProject(id='test',name='Test'));db.commit()
            with patch('app.api.v1.chat.DatasetManager.get_dataset',return_value=True), \
                 patch('app.api.v1.chat.MetadataService.get_profile',return_value={'columns':list(self.frame.columns)}), \
                 patch('app.llm.planner.QueryPlanner.plan_query',return_value={'intent':'SIMPLE','analysis_plan':{'source':{'tables':['fixture::Details']},'outputs':[{'id':'correlation','kind':'correlation','parameters':{'method':'pearson','columns':COLUMNS}}]}}), \
                 patch('app.llm.table_selector.TableSelector.select_tables',return_value={'tables_needed':['fixture::Details']}), \
                 patch('app.llm.agent.OllamaClient.call_model_chat',side_effect=replies), \
                 patch('app.analysis_engine.DatasetManager.load_dataset_dataframe',return_value=self.frame), patch('app.services.metadata_service.MetadataService.get_catalog_index',return_value={'tables':{'fixture::Details':{'columns':list(self.frame.columns)}},'relationships':[]}):
                response,failed=process_chat_message(ChatRequest(project_id='test',dataset_id='fixture::Details',message=QUESTION),db,lambda stage:None)
            self.assertFalse(failed,response)
            self.assertNotIn('Heatmaps unavailable',response['content'])
            self.assertNotIn('are statistically independent',response['content'])
            result=response['results']
            self.assertEqual(result['correlation']['columns'],COLUMNS)
            self.assertEqual(response['calculation']['steps'][0]['parameters']['columns'],COLUMNS)
            self.assertEqual(response['calculation']['steps'][0]['tables'],['fixture::Details'])
            saved=list_saved_analyses('test',db)
            self.assertEqual(saved[0]['result'],result)
            messages=list_project_messages('test',None,db)['messages']
            assistant=next(message for message in messages if message['role']=='assistant')
            self.assertEqual(json.loads(assistant['metadata_json'])['results'],result)
        engine.dispose()


class NorthwindCorrelationTest(unittest.TestCase):
    def test_full_northwind_matches_independent_centered_dot_products(self):
        path=Path(settings.DATASETS_DIR)/'northwind.db'
        with sqlite3.connect(f'file:{path}?mode=ro',uri=True) as db:
            values=np.array(db.execute('SELECT UnitPrice,Quantity,Discount FROM "Order Details"').fetchall(),dtype=float)
        centered=values-values.mean(axis=0)
        products=centered.T @ centered
        expected=products/np.sqrt(np.outer(np.diag(products),np.diag(products)))
        frame=pd.DataFrame(values,columns=COLUMNS)
        result=AnalysisEngine.execute_plan(None,'northwind.db::Order Details',{'correlation':True,'correlation_columns':COLUMNS},dataframe=frame)
        self.assertEqual(result['source_observation_count'],609283)
        self.assertEqual(result['row_count'],3)
        np.testing.assert_allclose(result['correlation']['matrix'],expected,atol=1e-12)
        np.testing.assert_allclose([[r[c] for c in COLUMNS] for r in result['data']],expected,atol=1e-12)


if __name__=='__main__':unittest.main()
