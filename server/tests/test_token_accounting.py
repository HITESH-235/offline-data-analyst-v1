"""Usage accounting with fake transports only; never spend model tokens."""
import io
import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError
from app.llm.client import OllamaClient
from app.llm.usage import report_usage
from app.services.request_control import RequestControl, current_request, model_metadata, RequestStopped
from app.core.config import settings


class TokenAccounting(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        workspace = patch.object(settings, 'WORKSPACE_DIR', self.tmp.name)
        workspace.start(); self.addCleanup(workspace.stop)
        no_network = patch('urllib.request.urlopen', side_effect=AssertionError('Live calls blocked'))
        no_network.start(); self.addCleanup(no_network.stop)
        self.control = RequestControl(30)
        token = current_request.set(self.control)
        self.addCleanup(current_request.reset, token)
        self.config = SimpleNamespace(OLLAMA_BASE_URL='http://fixture', OLLAMA_MODEL='local-fixture')
        config = patch('app.llm.client.settings', self.config)
        config.start(); self.addCleanup(config.stop)

    def body(self, usage=None, content='answer', **extra):
        value = {'response':content,'message':{'content':content}, **extra}
        if isinstance(usage,dict):
            for key,field in [('prompt_tokens','prompt_eval_count'),('completion_tokens','eval_count')]:
                if key in usage:value[field]=usage[key]
            details=usage.get('prompt_tokens_details')
            if isinstance(details,dict) and 'cached_tokens' in details:value['prompt_eval_cached_count']=details['cached_tokens']
        return io.BytesIO(json.dumps(value).encode())

    def call(self, response, **kwargs):
        opener = SimpleNamespace(open=lambda *a, **k: response)
        with patch('urllib.request.build_opener', return_value=opener):
            return OllamaClient.call_model('private-prompt-marker', system_prompt='system', **kwargs)

    def test_native_counts_persist_and_detail_subsets_are_not_added(self):
        response = self.body({'prompt_tokens':100, 'completion_tokens':30, 'total_tokens':130,
            'prompt_tokens_details':{'cached_tokens':80}, 'completion_tokens_details':{'reasoning_tokens':10},
            'unrelated':'must-not-be-saved'})
        self.assertEqual(self.call(response), 'answer')
        call = self.control.data['model_calls'][0]
        self.assertEqual(call['usage'], {'source':'provider', 'input_tokens':100, 'output_tokens':30,
            'total_tokens':130, 'cached_input_tokens':80, 'reasoning_tokens':None})
        self.assertEqual((call['provider'], call['model'], call['purpose']), ('ollama','local-fixture','generation'))
        self.assertGreaterEqual(call['duration_ms'], 0)
        from pathlib import Path
        saved = json.loads(next(Path(self.tmp.name).rglob(self.control.id+'.json')).read_text())
        self.assertEqual(saved['token_usage']['total_tokens']['reported_sum'], 130)
        for sensitive in ['private-prompt-marker','test-only-secret','must-not-be-saved','Authorization']:
            self.assertNotIn(sensitive, json.dumps(saved))

    def test_missing_usage_remains_unknown_and_zero_is_reported(self):
        self.call(self.body())
        self.call(self.body({'prompt_tokens':0, 'completion_tokens':0, 'total_tokens':0}))
        summary = self.control.data['token_usage']['total_tokens']
        self.assertEqual(summary, {'reported_sum':0, 'reported_calls':1, 'unknown_calls':1})
        self.assertIsNone(self.control.data['model_calls'][0]['usage']['input_tokens'])

    def test_invalid_usage_does_not_break_answer_or_create_fake_counts(self):
        for usage in ['bad', [], {'prompt_tokens':True, 'completion_tokens':-1, 'total_tokens':4.5,
                                'prompt_tokens_details':None, 'completion_tokens_details':'bad'}]:
            self.assertEqual(self.call(self.body(usage)), 'answer')
            self.assertEqual(self.control.data['model_calls'][-1]['usage']['source'], 'unavailable')

    def test_partial_usage_totals_have_known_and_unknown_coverage(self):
        self.call(self.body({'prompt_tokens':10, 'completion_tokens':5, 'total_tokens':15}))
        self.call(self.body({'completion_tokens':7}))
        summary = self.control.data['token_usage']
        self.assertEqual(summary['input_tokens'], {'reported_sum':10,'reported_calls':1,'unknown_calls':1})
        self.assertEqual(summary['output_tokens']['reported_sum'], 12)
        self.assertEqual(summary['total_tokens']['reported_sum'], 15)
        self.assertEqual(summary['total_tokens']['unknown_calls'], 1)

    def test_http_limit_is_one_call_with_unknown_usage(self):
        opener = SimpleNamespace(open=lambda *a, **k: self.fail('unused'))
        with patch('urllib.request.build_opener', return_value=opener), patch.object(opener, 'open',
                side_effect=HTTPError('http://fixture',429,'Limit',{},io.BytesIO(b'{}'))) as request:
            with self.assertRaisesRegex(ConnectionError, '429'):OllamaClient.call_model('question')
        self.assertEqual(request.call_count, 1)
        self.assertEqual(self.control.data['token_usage']['input_tokens']['unknown_calls'], 1)

    def test_unused_content_response_still_records_reported_usage(self):
        self.assertEqual(self.call(self.body({'prompt_tokens':12,'completion_tokens':0,'total_tokens':12}, content='')), '')
        self.assertEqual(self.control.data['token_usage']['total_tokens']['reported_sum'], 12)

    def test_ollama_generate_and_chat_report_native_counts(self):
        def response():return io.BytesIO(json.dumps({'response':'local answer','message':{'content':'chat answer'},
                'prompt_eval_count':11,'eval_count':18,'prompt_eval_cached_count':4}).encode())
        opener = SimpleNamespace(open=lambda *a, **k: response())
        with patch('urllib.request.build_opener', return_value=opener):
            self.assertEqual(OllamaClient.call_model('question'), 'local answer')
            self.assertEqual(OllamaClient.call_model_chat([{'role':'user','content':'question'}]), 'chat answer')
        calls = self.control.data['model_calls']
        self.assertEqual([c['purpose'] for c in calls], ['generation','agent_chat'])
        self.assertTrue(all(c['usage']['total_tokens']==29 for c in calls))
        self.assertEqual(self.control.data['token_usage']['total_tokens']['reported_sum'], 58)
        self.assertIsNone(calls[0]['usage']['reasoning_tokens'])

    def test_chat_purpose_and_scoped_metadata_do_not_leak_between_calls(self):
        opener = SimpleNamespace(open=lambda *a, **k: self.body({'prompt_tokens':2}))
        with patch('urllib.request.build_opener', return_value=opener):
            with model_metadata(purpose='planning', prompt_sections_characters={'question':8}):
                OllamaClient.call_model('question')
            OllamaClient.call_model_chat([{'role':'user','content':'next'}])
        calls = self.control.data['model_calls']
        self.assertEqual(calls[0]['purpose'],'planning')
        self.assertEqual(calls[1]['purpose'],'agent_chat')
        self.assertNotIn('prompt_sections_characters',calls[1])

    def test_deadline_keeps_usage_unknown_and_does_not_erase_reported_calls(self):
        self.call(self.body({'prompt_tokens':4,'completion_tokens':3,'total_tokens':7}))
        with self.assertRaises(RequestStopped):
            with self.control.model_call():self.control.stop('timed_out')
        summary = self.control.data['token_usage']['total_tokens']
        self.assertEqual(summary, {'reported_sum':7,'reported_calls':1,'unknown_calls':1})
        self.assertEqual(self.control.data['status'],'timed_out')

    def test_planner_repair_has_separate_usage_and_prompt_section_sizes(self):
        from app.llm.planner import QueryPlanner
        answers = [self.body({'prompt_tokens':100,'completion_tokens':20,'total_tokens':120}, content='invalid JSON'),
                   self.body({'prompt_tokens':150,'completion_tokens':30,'total_tokens':180},
                             content=json.dumps({'intent':'CONVERSATION','context_action':'standalone'}))]
        payloads = []
        def open_request(request, **kwargs):
            payloads.append(json.loads(request.data)); return answers.pop(0)
        with patch('urllib.request.build_opener', return_value=SimpleNamespace(open=open_request)), patch(
                'app.services.metadata_service.MetadataService.get_catalog_index', return_value={'tables':{},'relationships':[]}):
            result = QueryPlanner.plan_query('private-question-marker', {'columns':['value'],'dataset_id':'fixture'})
        self.assertEqual(result['intent'],'CONVERSATION')
        calls = self.control.data['model_calls']
        self.assertEqual([c['purpose'] for c in calls], ['planning','schema_repair'])
        self.assertEqual(calls[0]['prompt_sections_characters']['repair_addition'],0)
        self.assertGreater(calls[1]['prompt_sections_characters']['repair_addition'],0)
        self.assertEqual(self.control.data['token_usage']['total_tokens']['reported_sum'],300)
        self.assertNotIn('private-question-marker',json.dumps(self.control.data))
        for call,payload in zip(calls,payloads):
            self.assertEqual(set(payload),{'model','prompt','stream','system','format'})
            self.assertEqual(call['input_characters'],len(payload['prompt'])+len(payload['system']))

    def test_unknown_provider_and_no_request_are_harmless(self):
        token = current_request.set(None)
        try:
            usage = report_usage('unknown',{'usage':{'prompt_tokens':99}})
            self.assertEqual(usage['source'],'unavailable')
        finally:current_request.reset(token)


if __name__ == '__main__':unittest.main()
