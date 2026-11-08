import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.models.project import DBProject
from app.models.chat import ChatRequest, DBChatHistory
from app.storage.sqlite.session import Base
from app.api.v1.chat import process_chat_message, handle_chat_message


class ModelFailureCallsTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.db.add(DBProject(id='test',name='Test'));self.db.commit()
        self.request = ChatRequest(project_id='test',dataset_id='fixture',message='Calculate totals')
        self.stack = []
        for target, value in [
            ('app.api.v1.chat.DatasetManager.get_dataset',True),
            ('app.api.v1.chat.MetadataService.get_profile',{'columns':['Value']}),
            ('app.llm.table_selector.MetadataService.get_catalog_index',{'tables':{'fixture':{'columns':['Value']}},'relationships':[]}),
        ]:
            item=patch(target,return_value=value);item.start();self.stack.append(item)
    def tearDown(self):
        for item in reversed(self.stack):item.stop()
        self.db.close();self.engine.dispose()
    def response(self, content):
        return io.BytesIO(json.dumps({'response':json.dumps(content),'message':{'content':json.dumps(content)}}).encode())
    def limit(self):
        return HTTPError('http://ollama:11434/api/generate',503,'Unavailable',{},io.BytesIO(b'{}'))
    def run_sequence(self, sequence, count):
        with patch('app.llm.client.urllib.request.urlopen',side_effect=sequence) as provider:
            response,failed=process_chat_message(self.request,self.db,lambda stage:None)
        self.assertTrue(failed)
        self.assertEqual(provider.call_count,count)
        self.assertNotIn('results',response)
        self.assertEqual(self.db.query(DBChatHistory).count(),2)
        self.assertIn('Analysis stopped',response['content'])
        return response
    def test_planner_http_failure_stops_after_one_request(self):
        self.assertIn('503',self.run_sequence([self.limit()],1)['content'])
    def test_table_selection_http_failure_has_no_agent_request(self):
        self.run_sequence([self.response({'intent':'SIMPLE'}),self.limit()],2)
    def test_agent_http_failure_does_not_retry(self):
        self.run_sequence([self.response({'intent':'SIMPLE'}),self.response({'tables_needed':['fixture']}),self.limit()],3)
    def test_planner_network_failure_does_not_trigger_conversation(self):
        self.run_sequence([URLError('Unavailable')],1)
    def test_invalid_plan_does_not_trigger_conversation(self):
        self.run_sequence([self.response({'intent':'NOT_AN_INTENT'})],1)
    def test_invalid_selection_does_not_trigger_agent(self):
        self.run_sequence([self.response({'intent':'SIMPLE'}),self.response({'tables_needed':[]})],2)
    def test_legacy_json_endpoint_also_stops_after_one_call(self):
        with patch('app.llm.client.urllib.request.urlopen',side_effect=self.limit()) as provider:
            response=handle_chat_message(self.request,self.db)
        self.assertEqual(provider.call_count,1)
        self.assertIn('503',response['content'])
        self.assertNotIn('results',response)
    def test_stream_emits_failed_without_followup_model_call(self):
        import asyncio
        from sqlalchemy.pool import StaticPool
        from sqlalchemy.orm import sessionmaker
        from app.api.v1.chat import stream_chat_message
        engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
        Base.metadata.create_all(engine)
        factory=sessionmaker(bind=engine)
        with factory() as db:
            db.add(DBProject(id='test',name='Test'));db.commit()
        async def consume():
            response=await stream_chat_message(self.request)
            return [json.loads(line) async for line in response.body_iterator]
        try:
            with patch('app.api.v1.chat.SessionLocal',factory), patch('app.llm.client.urllib.request.urlopen',side_effect=self.limit()) as provider:
                events=asyncio.run(consume())
            self.assertEqual(events[-1]['stage'],'failed')
            self.assertEqual(provider.call_count,1)
            self.assertNotIn('results',events[-1]['result'])
            self.assertIn('503',events[-1]['result']['content'])
        finally:engine.dispose()

    def test_final_prose_without_calculation_is_incomplete(self):
        sequence=[self.response({'intent':'SIMPLE'}),self.response({'tables_needed':['fixture']}),self.response({'action':'final_answer','content':'Done'})]
        with patch('app.llm.client.urllib.request.urlopen',side_effect=sequence) as provider:
            response,failed=process_chat_message(self.request,self.db,lambda stage:None)
        self.assertTrue(failed);self.assertEqual(response['analysis_status'],'incomplete');self.assertNotIn('results',response);self.assertEqual(provider.call_count,3)

if __name__=='__main__':unittest.main()
