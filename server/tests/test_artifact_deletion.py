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
from app.models.chat import DBChatHistory
from app.services.chart_artifacts import persist_captures, artifact_file
from app.api.v1.projects import delete_saved_analysis

class ArtifactDeletionTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
  self.config=patch.object(settings,'WORKSPACE_DIR',str(self.root/'workspace'));self.config.start()
  source=self.root/'captures';source.mkdir()
  (source/'figure.json').write_text('{"data":[]}');(source/'figure.html').write_text('<html>Export</html>');(source/'image.png').write_bytes(bytes.fromhex('89504e470d0a1a0a'))
  (source/'captures.json').write_text(json.dumps([{'kind':'plotly','status':'ready','figure':'figure.json','download':'figure.html'},{'kind':'png','status':'ready','download':'image.png'}]))
  self.artifacts=persist_captures(source,'a');self.other=persist_captures(source,'a');self.other_project=persist_captures(source,'b')
  self.engine=create_engine('sqlite://');Base.metadata.create_all(self.engine);self.db=Session(self.engine)
  self.db.add_all([DBProject(id='a',name='A'),DBProject(id='b',name='B')])
  self.add('first',self.artifacts);self.add('unrelated',self.other);self.db.commit()
 def tearDown(self):
  self.db.close();self.engine.dispose();self.config.stop();self.tmp.cleanup()
 def add(self,ident,artifacts):
  self.db.add(DBChatHistory(id=ident,project_id='a',role='assistant',content='Original conversation',metadata_json=json.dumps({'question':'Original question','artifacts':artifacts,'calculation':{'steps':[]}})))
 def paths(self,artifacts,project='a'):
  root=self.root/'workspace'/'projects'/project/'charts'
  return [p for p in root.iterdir() if any(p.name.startswith(artifact['id']) for artifact in artifacts)]
 def test_delete_removes_json_html_png_and_manifests_only_for_that_analysis(self):
  paths=self.paths(self.artifacts);self.assertEqual(len(paths),5)
  delete_saved_analysis('a','first',self.db)
  self.assertTrue(all(not path.exists() for path in paths))
  self.assertEqual(len(self.paths(self.other)),5);self.assertEqual(len(self.paths(self.other_project,'b')),5)
  row=self.db.get(DBChatHistory,'first');self.db.refresh(row)
  self.assertEqual(row.content,'Original conversation');meta=json.loads(row.metadata_json)
  self.assertEqual(meta['question'],'Original question');self.assertIn('calculation',meta);self.assertTrue(meta['analysis_deleted'])
  with self.assertRaises(FileNotFoundError):artifact_file('a',self.artifacts[0]['id'],'download')
 def test_shared_artifact_survives_until_last_analysis_reference_is_deleted(self):
  self.add('shared',[self.artifacts[0]]);self.db.commit()
  delete_saved_analysis('a','first',self.db)
  self.assertEqual(len(self.paths([self.artifacts[0]])),3);self.assertEqual(len(self.paths([self.artifacts[1]])),0)
  delete_saved_analysis('a','shared',self.db)
  self.assertEqual(self.paths(self.artifacts),[])
 def test_failed_database_commit_restores_files_and_saved_record(self):
  paths=self.paths(self.artifacts)
  with patch.object(self.db,'commit',side_effect=RuntimeError('Commit failed')):
   with self.assertRaises(RuntimeError):delete_saved_analysis('a','first',self.db)
  self.assertTrue(all(path.exists() for path in paths))
  self.assertIn('artifacts',json.loads(self.db.get(DBChatHistory,'first').metadata_json))
 def test_missing_file_and_repeated_deletion_are_safe(self):
  self.paths(self.artifacts)[0].unlink()
  delete_saved_analysis('a','first',self.db);delete_saved_analysis('a','first',self.db)
  self.assertEqual(self.paths(self.artifacts),[])
 def test_untrusted_manifest_cannot_delete_another_artifacts_file(self):
  root=self.root/'workspace'/'projects'/'a'/'charts'
  manifest=root/(self.artifacts[0]['id']+'.artifact.json')
  meta=json.loads(manifest.read_text());meta['files']['download']=self.other[0]['id']+'-download.html';manifest.write_text(json.dumps(meta))
  delete_saved_analysis('a','first',self.db)
  self.assertEqual(len(self.paths(self.other)),5)
