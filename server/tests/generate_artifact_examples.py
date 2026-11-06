"""Temporary end-to-end visual examples. Remove the project after browser checks."""
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch
from app.core.config import settings
from app.storage.sqlite.session import SessionLocal
from app.services.project_service import ProjectService
from app.models.chat import ChatRequest
from app.api.v1.chat import process_chat_message
from artifact_examples import EXAMPLES

with SessionLocal() as db, tempfile.TemporaryDirectory() as directory:
 project=ProjectService.create_project(db,'Artifact delivery verification')
 Path(directory,'artifact_fixture.csv').write_text('x,y\n1,2\n2,4\n')
 with patch.object(settings,'DATASETS_DIR',directory),patch('app.api.v1.chat.QueryPlanner.plan_query',return_value={'intent':'COMPLEX'}),patch('app.llm.agent.DatasetManager.get_dataset',return_value=True),patch('app.llm.agent.MetadataService.get_profile',return_value={'columns':['x','y']}),patch('app.llm.table_selector.TableSelector.select_tables',return_value={'tables_needed':['artifact_fixture.csv']}):
  report=[]
  for name,code in EXAMPLES.items():
   if os.environ.get("ARTIFACT_EXAMPLES") and name not in os.environ["ARTIFACT_EXAMPLES"].split(","): continue
   replies=[json.dumps({'action':'tool_call','tool':'run_code','parameters':{'code':code}}),json.dumps({'action':'final_answer','content':'Controlled '+name+' generated'})]
   with patch('app.llm.agent.OllamaClient.call_model_chat',side_effect=replies):
    result,failed=process_chat_message(ChatRequest(project_id=project.id,dataset_id='artifact_fixture.csv',message='Controlled '+name),db,lambda stage:None)
   report.append({'example':name,'failed':failed,'artifacts':result.get('artifacts',[])})
  # Consecutive identical names must also remain independent.
  manifest={'project_id':project.id,'examples':report}
  Path('/tmp/artifact-example-manifest.json').write_text(json.dumps(manifest))
  print(json.dumps(manifest))
