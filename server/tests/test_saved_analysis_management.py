import json
import unittest
from datetime import datetime
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.storage.sqlite.session import Base
from app.models.project import DBProject
from app.models.chat import DBChatHistory
from app.api.v1.projects import delete_saved_analysis, list_project_messages, list_saved_analyses

class SavedAnalysisManagementTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.db.add_all([DBProject(id='a',name='A'),DBProject(id='b',name='B')])
        for i in range(55):
            self.db.add(DBChatHistory(id=f'{i:03}',project_id='a',role='assistant' if i==54 else 'user',content=f'Message {i}',created_at=datetime(2026,1,1),metadata_json=json.dumps({'question':'Question','results':{'columns':['Value'],'data':[{'Value':10}]},'calculation':{'steps':[]}}) if i==54 else None))
        self.db.commit()
    def tearDown(self):
        self.db.close();self.engine.dispose()
    def test_delete_removes_result_and_preserves_chat_project_and_trace(self):
        delete_saved_analysis('a','054',self.db)
        self.assertEqual(list_saved_analyses('a',self.db),[])
        row=self.db.get(DBChatHistory,'054');self.db.refresh(row)
        self.assertEqual(row.content,'Message 54')
        meta=json.loads(row.metadata_json)
        self.assertNotIn('results',meta);self.assertEqual(meta['question'],'Question');self.assertIn('calculation',meta)
        self.assertIsNotNone(self.db.get(DBProject,'a'))
        self.assertEqual(self.db.query(DBChatHistory).count(),55)
    def test_wrong_project_cannot_delete_result(self):
        with self.assertRaises(HTTPException) as caught:delete_saved_analysis('b','054',self.db)
        self.assertEqual(caught.exception.status_code,404)
        self.assertEqual(len(list_saved_analyses('a',self.db)),1)
    def test_history_pagination_has_no_gaps_or_duplicates_with_same_timestamps(self):
        latest=list_project_messages('a',None,self.db)
        older=list_project_messages('a',latest['before'],self.db)
        self.assertTrue(latest['has_more']);self.assertFalse(older['has_more'])
        self.assertEqual([row['id'] for row in older['messages']+latest['messages']],[f'{i:03}' for i in range(55)])
        self.assertEqual(list_project_messages('b',None,self.db)['messages'],[])
    def test_cursor_is_project_scoped(self):
        with self.assertRaises(HTTPException):list_project_messages('b','054',self.db)

if __name__=='__main__':unittest.main()
