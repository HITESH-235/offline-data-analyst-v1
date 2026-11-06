import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.core.config import settings
from app.storage.sqlite.session import Base
from app.models.project import DBProject
from app.models.chat import ChatRequest
from app.api.v1.chat import process_chat_message
from app.api.v1.projects import list_saved_analyses, list_project_messages, read_chart_artifact
from app.services.chart_artifacts import artifact_file
from artifact_examples import EXAMPLES

class ChartArtifactTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
  (self.root/'fixture.csv').write_text('x,y\n1,2\n2,4\n')
  self.engine=create_engine('sqlite://');Base.metadata.create_all(self.engine);self.db=Session(self.engine)
  self.db.add(DBProject(id='test',name='Test'));self.db.commit()
  self.patches=[patch.object(settings,'WORKSPACE_DIR',str(self.root/'workspace')),patch.object(settings,'DATASETS_DIR',str(self.root)),
   patch('app.api.v1.chat.QueryPlanner.plan_query',return_value={'intent':'COMPLEX'}),
   patch('app.llm.agent.DatasetManager.get_dataset',return_value=True),
   patch('app.llm.agent.MetadataService.get_profile',return_value={'columns':['x','y']}),
   patch('app.llm.table_selector.TableSelector.select_tables',return_value={'tables_needed':['fixture.csv']})]
  for item in self.patches:item.start()
 def tearDown(self):
  for item in reversed(self.patches):item.stop()
  self.db.close();self.engine.dispose();self.tmp.cleanup()
 def run_example(self,name):
  replies=[json.dumps({'action':'tool_call','tool':'run_code','parameters':{'code':EXAMPLES[name]}}),json.dumps({'action':'final_answer','content':'Controlled '+name})]
  with patch('app.llm.agent.OllamaClient.call_model_chat',side_effect=replies) as model:
   result,failed=process_chat_message(ChatRequest(project_id='test',dataset_id='fixture.csv',message='Controlled '+name),self.db,lambda stage:None)
  self.assertFalse(failed,result);self.assertEqual(model.call_count,2)
  self.assertNotIn('chart_base64',result)
  return result
 def test_real_plotly_path_persists_and_restores_without_overwrite(self):
  first=self.run_example('line');second=self.run_example('line')
  a,b=first['artifacts'][0],second['artifacts'][0]
  self.assertNotEqual(a['id'],b['id'])
  for artifact in (a,b):
   path,_=artifact_file('test',artifact['id'],'figure');fig=json.loads(path.read_text())
   self.assertEqual(len(fig['data']),2);self.assertIn('annotations',fig['layout'])
   export,_=artifact_file('test',artifact['id'],'download')
   self.assertIn('plotly.js v',export.read_text());self.assertGreater(export.stat().st_size,4000000)
  saved=list_saved_analyses('test',self.db);self.assertEqual(len(saved),2)
  self.assertEqual(saved[0]['tables'],['fixture.csv']);self.assertEqual(saved[0]['calculation']['steps'][0]['tool'],'run_code')
  past=list_project_messages('test',None,self.db)['messages'];self.assertEqual(len([m for m in past if 'artifacts' in (m['metadata_json'] or '')]),2)
  response=read_chart_artifact('test',a['id'],'download',self.db)
  self.assertIn('attachment',response.headers['content-disposition'])
 def test_real_png_and_empty_outputs(self):
  png=self.run_example('png')['artifacts'][0];self.assertEqual(png['kind'],'png')
  path,_=artifact_file('test',png['id'],'image');self.assertEqual(path.read_bytes()[:8],b'\x89PNG\r\n\x1a\n')
  empty=self.run_example('empty')['artifacts'][0];self.assertEqual(empty['status'],'empty');self.assertIn('download_url',empty)
  self.assertEqual(self.run_example('no_chart')['artifacts'],[])
  with patch.dict(EXAMPLES, {'empty_trace': 'fig=go.Figure(go.Scatter(x=[],y=[]))'}):
   self.assertEqual(self.run_example('empty_trace')['artifacts'][0]['status'],'empty')
 def test_capture_failure_retains_a_download_instead_of_blank_plot(self):
  artifact=self.run_example('capture_failed')['artifacts'][0]
  self.assertEqual(artifact['status'],'download_only')
  self.assertNotIn('figure_url',artifact)
  export,_=artifact_file('test',artifact['id'],'download');self.assertTrue(export.exists())

 def test_chart_survives_explanation_provider_failure(self):
  replies=[json.dumps({'action':'tool_call','tool':'run_code','parameters':{'code':EXAMPLES['line']}}),RuntimeError('Provider unavailable')]
  with patch('app.llm.agent.OllamaClient.call_model_chat',side_effect=replies) as model:
   response,failed=process_chat_message(ChatRequest(project_id='test',dataset_id='fixture.csv',message='Controlled line'),self.db,lambda stage:None)
  self.assertFalse(failed);self.assertEqual(model.call_count,2)
  self.assertEqual(len(response['artifacts']),1)
  self.assertIn('could not prepare',response['content'])
  self.assertEqual(len(list_saved_analyses('test',self.db)),1)

 def test_artifact_path_is_project_scoped(self):
  artifact=self.run_example('pie')['artifacts'][0]
  with self.assertRaises(FileNotFoundError):artifact_file('other',artifact['id'],'figure')
  with self.assertRaises(FileNotFoundError):artifact_file('test','../escape','figure')
