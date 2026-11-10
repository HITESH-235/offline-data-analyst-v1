"""Fresh correlation responses through actual Python execution, with no provider calls."""
import json
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.api.v1.chat import process_chat_message
from app.api.v1.projects import list_saved_analyses, list_project_messages
from app.core.config import settings
from app.models.chat import ChatRequest
from app.models.project import DBProject
from app.sandbox.runner import SandboxRunner
from app.storage.sqlite.session import Base

COLUMNS=['UnitPrice','Quantity','Discount']
QUESTION='Show a correlation heatmap of UnitPrice, Quantity, and Discount'
REQUEST={'columns':COLUMNS,'method':'pearson'}
PNG_CODE="""corr = df[['UnitPrice','Quantity','Discount']].corr()
plt.figure(figsize=(8,6))
sns.heatmap(corr, annot=True, cmap='coolwarm', center=0, fmt='.3f')
plt.savefig('output_chart.png')
print(corr)
"""
PLOTLY_CODE="""corr = df[['UnitPrice','Quantity','Discount']].corr()
fig=go.Figure(go.Heatmap(x=list(corr.columns),y=list(corr.index),z=corr.values))
fig.write_html('output_chart.html')
"""


class PythonCorrelationTest(unittest.TestCase):
    def setUp(self):
        self.frame=pd.DataFrame({'UnitPrice':[1.,4.,2.,8.,3.],'Quantity':[3,1,4,2,5], 'Discount':[.1,0.,.2,.1,.15]})

    def test_fresh_png_and_plotly_responses_include_persisted_matrix(self):
        engine=create_engine('sqlite://')
        Base.metadata.create_all(engine)
        with tempfile.TemporaryDirectory() as directory, Session(engine) as db,patch.object(settings,'WORKSPACE_DIR',directory):
            db.add(DBProject(id='test',name='Test'));db.commit()
            ids=[]
            for code,kind in [(PNG_CODE,'png'),(PLOTLY_CODE,'plotly'),("corr=df[['UnitPrice','Quantity','Discount']].corr()",None)]:
                replies=[json.dumps({'action':'tool_call','tool':'run_code','parameters':{'code':code}}),json.dumps({'action':'final_answer','content':'Only a PNG is available. The measures are independent.'})]
                with patch('app.api.v1.chat.QueryPlanner.plan_query',return_value={'intent':'COMPLEX'}), \
                     patch('app.llm.table_selector.TableSelector.select_tables',return_value={'tables_needed':['fixture::Details']}), \
                     patch('app.llm.agent.DatasetManager.get_dataset',return_value=True), \
                     patch('app.llm.agent.MetadataService.get_profile',return_value={'columns':COLUMNS}), \
                     patch('app.llm.agent.DatasetManager.load_joined_dataframe',return_value=self.frame), \
                     patch('app.llm.agent.OllamaClient.call_model_chat',side_effect=replies):
                    response,failed=process_chat_message(ChatRequest(project_id='test',dataset_id='fixture::Details',message=QUESTION),db,lambda stage:None)
                self.assertFalse(failed,response)
                ids.append(response['id'])
                self.assertEqual(response['type'],'table')
                result=response['results']
                self.assertEqual(result['row_count'],3)
                self.assertEqual(result['correlation']['columns'],COLUMNS)
                self.assertEqual(result['source_observation_count'],5)
                np.testing.assert_allclose(result['correlation']['matrix'],self.frame.corr().values)
                if kind:
                    self.assertEqual(response['artifacts'][0]['kind'],kind)
                else:
                    self.assertEqual(response['artifacts'],[])
                self.assertEqual(response['calculation']['steps'][0]['tool'],'run_code')
                self.assertEqual(response['calculation']['steps'][0]['parameters']['code'],code)
                self.assertIn('verified heatmap',response['content']);self.assertIn('Open result → Chart',response['content'])
                self.assertNotIn('Only a PNG',response['content'])
            self.assertEqual(len(set(ids)),3)
            saved=list_saved_analyses('test',db)
            self.assertEqual(len(saved),3)
            for item in saved:
                self.assertEqual(item['result']['analysis_kind'],'correlation')
                self.assertEqual(item['tables'],['fixture::Details'])
            history=list_project_messages('test',None,db)['messages']
            for message in history:
                if message['role']=='assistant':
                    metadata=json.loads(message['metadata_json'])
                    self.assertEqual(metadata['results']['row_count'],3)
        engine.dispose()

    def test_png_without_matrix_or_wrong_population_fails_before_persistence(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(settings,'WORKSPACE_DIR',directory):
            for code in ['plt.plot([1,2],[2,4])',"corr=df.head(3).corr()\nsns.heatmap(corr)"]:
                output=SandboxRunner.run_code('fixture',code,'test',dataframe=self.frame,correlation_request=REQUEST)
                try:
                    self.assertFalse(output['success'])
                    self.assertIn('requested correlation matrix',output['error'])
                    self.assertEqual(output['artifacts'],[])
                    self.assertIsNone(output['results'])
                finally:SandboxRunner.cleanup(output)


if __name__=='__main__':unittest.main()
