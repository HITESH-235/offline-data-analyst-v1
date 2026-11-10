"""Controlled deadlines; no external model requests."""
import asyncio
import json
import tempfile
import threading
import time
import unittest
import urllib.request
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.api.v1.chat import handle_chat_message, stream_chat_message, supervised_events
from app.core.config import settings
from app.models.chat import ChatRequest, DBChatHistory
from app.models.project import DBProject
from app.services.analysis_context import load_context
from app.services.request_control import RequestControl, current_request, checkpoint
from app.storage.sqlite.session import Base


class RequestDeadlineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_engine('sqlite:///' + self.tmp.name + '/test.db', connect_args={'check_same_thread': False})
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine)
        with self.factory() as db:
            db.add(DBProject(id='test', name='Test'))
            db.commit()
            db.add(DBChatHistory(id='last-success', project_id='test', role='assistant', content='verified result',
                metadata_json=json.dumps({'question':'baseline', 'analysis_failed':False,
                'calculation': {'steps':[{'status':'succeeded','tool':'comparison_summary','tables':['fixture']}]},
                'analysis_context':{'source':{'tables':['fixture']},'metric':'late_percentage'}})))
            db.commit()
            self.context = load_context(db, 'test')
        self.stack = ExitStack()
        self.stack.enter_context(patch('app.api.v1.chat.SessionLocal', self.factory))
        self.stack.enter_context(patch.object(settings, 'WORKSPACE_DIR', self.tmp.name))
        self.stack.enter_context(patch.object(settings, 'CHAT_REQUEST_TIMEOUT_SECONDS', 0.08))
        self.stack.enter_context(patch('app.api.v1.chat.DatasetManager.get_dataset', return_value=True))
        self.stack.enter_context(patch('app.api.v1.chat.MetadataService.get_profile', return_value={'columns':['value']}))
        self.stack.enter_context(patch('app.api.v1.chat.MetadataService.get_catalog_index', return_value={'tables':{}}))
        self.request = ChatRequest(project_id='test', dataset_id='fixture', message='Analyze totals')
        self.release = threading.Event()
        self.finished = threading.Event()

    def tearDown(self):
        self.release.set()
        self.stack.close()
        self.engine.dispose()
        self.tmp.cleanup()

    def assert_context_preserved(self):
        with self.factory() as db:
            self.assertEqual(load_context(db, 'test'), self.context)
            self.assertEqual(db.query(DBChatHistory).filter_by(role='assistant').count(), 1)

    def slow(self, *args, **kwargs):
        self.release.wait(2)
        self.finished.set()
        return {'intent':'CONVERSATION'}

    def test_json_slow_planner_is_bounded_and_late_result_is_fenced(self):
        with patch('app.api.v1.chat.QueryPlanner.plan_query', side_effect=self.slow) as planner, patch('app.api.v1.chat.Agent.run', return_value={'content':'late success','type':'text'}) as agent:
            started = time.monotonic()
            response = asyncio.run(handle_chat_message(self.request))
            self.assertLess(time.monotonic() - started, 0.5)
            self.assertEqual(response.status_code, 504)
            self.assertEqual(json.loads(response.body)['analysis_status'], 'timed_out')
            self.release.set()
            self.assertTrue(self.finished.wait(1))
            time.sleep(0.04)
            self.assert_context_preserved()
            self.assertEqual(planner.call_count, 1)
            # No subsequent model/tool call after the blocked planner returns.
            agent.assert_not_called()

    def test_stream_slow_execution_has_terminal_timeout_without_late_success(self):
        def execute(**kwargs):
            self.release.wait(2)
            self.finished.set()
            return {'content':'late success','type':'text'}
        async def consume():
            response = await stream_chat_message(self.request)
            return [json.loads(line) async for line in response.body_iterator]
        with patch('app.api.v1.chat.QueryPlanner.plan_query', return_value={'intent':'CONVERSATION'}), patch('app.api.v1.chat.Agent.run', side_effect=execute):
            started = time.monotonic()
            events = asyncio.run(consume())
            self.assertLess(time.monotonic() - started, 0.5)
            self.assertEqual(events[-1]['stage'], 'timed_out')
            self.assertNotIn('completed', [e['stage'] for e in events])
            self.release.set()
            self.assertTrue(self.finished.wait(1))
            time.sleep(0.04)
            self.assert_context_preserved()

    def test_disconnect_cancels_registered_work_and_fences_publication(self):
        closed = threading.Event()
        registered = threading.Event()
        def planner(*args, **kwargs):
            with current_request.get().resource(closed.set):
                registered.set()
                self.release.wait(2)
            self.finished.set()
            return {'intent':'CONVERSATION'}
        async def disconnect():
            response = await stream_chat_message(self.request)
            iterator = response.body_iterator
            await anext(iterator)
            self.assertTrue(await asyncio.to_thread(registered.wait, 1))
            await iterator.aclose()
        with patch('app.api.v1.chat.QueryPlanner.plan_query', side_effect=planner):
            asyncio.run(disconnect())
            self.assertTrue(closed.wait(1))
            self.release.set()
            self.assertTrue(self.finished.wait(1))
            time.sleep(0.04)
            self.assert_context_preserved()

    def test_slow_finalization_cannot_publish_after_deadline(self):
        def finalize(*args):
            self.release.wait(2)
            self.finished.set()
            return {'type':'text', 'content':'late finalized result'}
        with patch('app.api.v1.chat.QueryPlanner.plan_query', return_value={'intent':'SIMPLE'}), patch('app.api.v1.chat.Agent.run', return_value={'type':'text','content':'result'}), patch('app.services.analysis_package.finalize', side_effect=finalize):
            response = asyncio.run(handle_chat_message(self.request))
            self.assertEqual(response.status_code, 504)
            self.release.set()
            self.assertTrue(self.finished.wait(1))
            time.sleep(0.04)
            self.assert_context_preserved()

    def test_schema_repair_shares_original_budget_and_call_timings(self):
        calls = []
        def model(*args, **kwargs):
            control = current_request.get()
            calls.append(control)
            try:
                with control.model_call():
                    time.sleep(0.10)
                return json.dumps({'intent':'INVALID' if len(calls) == 1 else 'CONVERSATION'})
            finally:
                if len(calls) == 2: self.finished.set()
        with patch.object(settings, 'CHAT_REQUEST_TIMEOUT_SECONDS', 0.16), patch('app.llm.planner.OllamaClient.call_model', side_effect=model):
            started = time.monotonic()
            response = asyncio.run(handle_chat_message(self.request))
            self.assertEqual(response.status_code, 504)
            self.assertLess(time.monotonic() - started, 0.5)
            self.assertTrue(self.finished.wait(1))
            self.assertEqual(len(calls), 2)
            self.assertIs(calls[0], calls[1])
            self.assertEqual(calls[0].data['model_call_count'], 2)
            self.assertTrue(all('duration_ms' in call for call in calls[0].data['model_calls']))
            self.assert_context_preserved()

    def test_normal_json_and_stream_still_publish(self):
        async def normal():
            result = await handle_chat_message(self.request)
            response = await stream_chat_message(self.request)
            events = [json.loads(line) async for line in response.body_iterator]
            return result, events
        with patch.object(settings, 'CHAT_REQUEST_TIMEOUT_SECONDS', 2), patch('app.api.v1.chat.QueryPlanner.plan_query', return_value={'intent':'CONVERSATION'}), patch('app.api.v1.chat.Agent.run', return_value={'content':'hello','type':'text'}):
            result, events = asyncio.run(normal())
        self.assertEqual(result['content'], 'hello')
        self.assertEqual(events[-1]['stage'], 'completed')
        with self.factory() as db:
            self.assertEqual(db.query(DBChatHistory).filter_by(role='assistant').count(), 3)
        records = [json.loads(p.read_text()) for p in Path(self.tmp.name, 'evaluations/request-deadlines').glob('*.json')]
        self.assertEqual(len(records), 2)
        self.assertTrue(all(r['status'] == 'completed' for r in records))

    def test_sandbox_process_is_killed_on_cancellation(self):
        import subprocess
        from app.sandbox.runner import SandboxRunner
        original_popen = subprocess.Popen
        processes = []
        started = threading.Event()
        done = threading.Event()
        control = RequestControl(2)
        def popen(*args, **kwargs):
            process = original_popen([__import__('sys').executable, '-c', 'import time; time.sleep(30)'],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            processes.append(process)
            started.set()
            return process
        def run():
            token = current_request.set(control)
            try:
                SandboxRunner.run_code('fixture', 'result = 1')
            except BaseException:
                pass
            finally:
                current_request.reset(token)
                done.set()
        with patch('app.sandbox.runner.SandboxRunner._resolve_dataset_path', return_value='/tmp/fixture.csv'), patch('app.sandbox.runner.subprocess.Popen', side_effect=popen), patch('app.sandbox.runner.persist_captures', create=True) as captures:
            thread = threading.Thread(target=run, daemon=True)
            thread.start()
            self.assertTrue(started.wait(1))
            control.stop('cancelled')
            self.assertTrue(done.wait(1))
            self.assertEqual(processes[0].returncode, -9)
            captures.assert_not_called()

    def test_socket_is_closed_during_stalled_headers_and_body(self):
        from app.llm.client import provider_response
        for send_headers in (False, True):
            with self.subTest(send_headers=send_headers):
                connected = threading.Event()
                peer_closed = threading.Event()
                class Handler(BaseHTTPRequestHandler):
                    def log_message(self, *args): pass
                    def do_GET(self):
                        if send_headers:
                            self.send_response(200)
                            self.send_header('Content-Length', '100000')
                            self.end_headers()
                            self.wfile.write(b'{')
                            self.wfile.flush()
                        connected.set()
                        self.connection.settimeout(2)
                        try:
                            if self.connection.recv(1) == b'': peer_closed.set()
                        except OSError:
                            pass
                server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
                threading.Thread(target=server.serve_forever, daemon=True).start()
                control = RequestControl(2)
                worker_done = threading.Event()
                def call():
                    token = current_request.set(control)
                    try:
                        with provider_response(urllib.request.Request(f'http://127.0.0.1:{server.server_port}/'), 10) as response:
                            response.read()
                    except BaseException:
                        pass
                    finally:
                        current_request.reset(token)
                        worker_done.set()
                thread = threading.Thread(target=call, daemon=True)
                thread.start()
                try:
                    self.assertTrue(connected.wait(1))
                    control.stop('timed_out')
                    self.assertTrue(peer_closed.wait(0.5))
                    self.assertTrue(worker_done.wait(0.5))
                    self.assertEqual(len(control.data['model_calls']), 1)
                    self.assertIn('duration_ms', control.data['model_calls'][0])
                finally:
                    server.shutdown()
                    server.server_close()

class ProgressStagesTest(unittest.TestCase):
    def test_progress_is_ordered_and_unsupported_is_terminal(self):
        from app.services.request_control import report_progress
        stages=['planning','repairing_plan','selecting_tables','running_tool','validating','preparing_answer','publishing']
        def work(request,db,emit):
            for stage in stages:report_progress(stage)
            return {'analysis_status':'unsupported','content':'Unsupported calculation'},True
        async def consume(control):return [event async for event in supervised_events(None,control)]
        with tempfile.TemporaryDirectory() as directory,patch.object(settings,'WORKSPACE_DIR',directory),patch('app.api.v1.chat.process_chat_message',side_effect=work):
            events=asyncio.run(consume(RequestControl(2)))
        self.assertEqual([event['stage'] for event in events],stages+['unsupported'])
        self.assertTrue(all(event['elapsed_ms']>=0 for event in events))
