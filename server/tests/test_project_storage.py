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
from app.services.project_service import ProjectService
from app.utils.workspace import get_project_dir, verify_project_structure

class ProjectStorageTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = patch.object(settings, 'WORKSPACE_DIR', self.temp.name)
        self.config.start()
        self.engine = create_engine('sqlite://')
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
    def tearDown(self):
        self.db.close();self.engine.dispose();self.config.stop();self.temp.cleanup()
    def file(self, directory, content):
        path = Path(self.temp.name)/'projects'/directory/'charts'/'output_chart.html'
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(content);return path
    def test_create_rename_and_delete_share_id_folder(self):
        p=ProjectService.create_project(self.db,'Test name')
        chart=self.file(p.id,'chart')
        self.db.add(DBChatHistory(id='chat',project_id=p.id,role='user',content='Keep scoped'))
        self.db.commit()
        ProjectService.rename_project(self.db,p.id,'New name')
        self.assertTrue(chart.exists());self.assertTrue(verify_project_structure(p.id))
        self.assertEqual(ProjectService.load_metadata(p.id)['name'],'New name')
        ProjectService.delete_project(self.db,p.id)
        self.assertFalse(chart.parent.parent.exists())
        self.assertEqual(self.db.query(DBChatHistory).count(),0)
    def test_chart_and_report_generators_use_same_id_directory(self):
        import pandas as pd
        from app.services.chart_engine import ChartEngine
        from app.services.report_service import ReportService
        project=ProjectService.create_project(self.db,'Visible name')
        chart=ChartEngine.generate_and_save_chart(self.db,project.id,pd.DataFrame({'Month':['Jan'],'Revenue':[10]}),'line','Month','Revenue')
        self.assertEqual(Path(chart).parent,Path(get_project_dir(project.id))/'charts')
        ReportService.generate_report(self.db,project.id,'Simple report','Revenue: 10')
        self.assertTrue(list((Path(get_project_dir(project.id))/'reports').glob('*.pdf')))
        self.assertFalse((Path(self.temp.name)/'projects'/'Visible_name').exists())

    def test_invalid_id_cannot_escape_workspace(self):
        for ident in ('../x','','a/b','..'):
            with self.assertRaises(ValueError):get_project_dir(ident)
