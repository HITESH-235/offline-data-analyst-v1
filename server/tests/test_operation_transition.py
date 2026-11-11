"""Explicit typed operation replacement, captured count-to-lateness follow-up."""
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.analysis.operations import validate_plan
from app.services.specification_context import validate_followup
from app.models.chat import ChatRequest, DBChatHistory
from app.models.project import DBProject
from app.storage.sqlite.session import Base
from app.api.v1.chat import process_chat_message
from app.llm.planner import QueryPlanner

FIX = json.loads((Path(__file__).parent/'fixtures/operation_transition_failure.json').read_text())
REF = FIX['reference']
KEY = FIX['baseline']['outputs'][0]['id']
HISTORY = {'recent_successes': [{'message_id': REF, 'analysis': {'plan': FIX['baseline']}}]}

class OperationTransition(unittest.TestCase):
    def test_missing_single_output_reference_and_declarations_repair_without_semantic_change(self):
        capture=json.loads((Path(__file__).parent/'fixtures/single_output_followup_failure.json').read_text())
        history={'recent_successes':[{'message_id':capture['reference'],'analysis':{'version':1,'plan':capture['baseline']}}]}
        old=capture['baseline']['outputs'][0]['id']
        corrected=copy.deepcopy(capture['draft'])
        corrected['analysis_plan']['outputs'][0]['reference_output_id']=old
        corrected['analysis_plan']['outputs'][0].pop('id',None)
        corrected['changed_fields']=[f'outputs.{old}.kind',f'outputs.{old}.parameters']
        for changes_population in (False,True):
            repaired=copy.deepcopy(corrected)
            if changes_population:repaired['analysis_plan']['outputs'][0]['parameters']['eligibility_filters'][1]['value']='2019-01-01'
            diagnostics=[]
            with self.subTest(changes_population=changes_population),patch('app.llm.client.OllamaClient.call_model',side_effect=[json.dumps(capture['draft']),json.dumps(repaired)]) as model:
                if changes_population:
                    with self.assertRaises(ValueError):QueryPlanner.plan_query('What percentage of those arrived late?',{'columns':[]},history,diagnostics)
                else:
                    result=QueryPlanner.plan_query('What percentage of those arrived late?',{'columns':[]},history,diagnostics)
                    self.assertEqual(result['analysis_plan']['outputs'][0]['id'],old)
                    self.assertEqual(result['analysis_plan']['outputs'][0]['parameters']['eligibility_filters'],capture['draft']['analysis_plan']['outputs'][0]['parameters']['eligibility_filters'])
                self.assertEqual(model.call_count,2)

    def draft(self):
        d = copy.deepcopy(FIX['draft'])
        d['changed_fields'] = [f'outputs.{KEY}.kind', f'outputs.{KEY}.parameters']
        return d

    def test_explicit_replacement_preserves_baseline_and_other_fields(self):
        original = copy.deepcopy(HISTORY)
        d = validate_plan(self.draft(), history=HISTORY)
        validate_followup(d['analysis_plan'], HISTORY, REF, d['changed_fields'])
        self.assertEqual(d['analysis_plan']['outputs'][0]['id'], KEY)
        self.assertEqual(HISTORY, original)
        d['analysis_plan']['chart_scope']['preference'] = 'auto'
        with self.assertRaises(ValueError):
            validate_followup(d['analysis_plan'], HISTORY, REF, d['changed_fields'])

    def test_incomplete_declarations_and_wrong_parameter_schema_reject(self):
        for paths in ([], [f'outputs.{KEY}.kind'], [f'outputs.{KEY}.parameters']):
            d = self.draft(); d['changed_fields'] = paths
            with self.assertRaises(ValueError): validate_plan(d, history=HISTORY)
        d = self.draft(); d['analysis_plan']['outputs'][0]['parameters'] = FIX['baseline']['outputs'][0]['parameters']
        with self.assertRaises(ValueError): validate_plan(d, history=HISTORY)

    def test_captured_followup_executes_offline(self):
        engine = create_engine('sqlite://'); Base.metadata.create_all(engine)
        with Session(engine) as db:
            db.add(DBProject(id='transition', name='Transition'))
            metadata = {'analysis_context': {'version': 1, 'plan': FIX['baseline']},
                        'calculation': {'steps': [{'tool': 'aggregation', 'status': 'succeeded'}]}}
            db.add(DBChatHistory(id=REF, project_id='transition', role='assistant', type='table', content='Prior count.', metadata_json=json.dumps(metadata)))
            db.commit()
            with patch('urllib.request.urlopen', side_effect=AssertionError('No network')), patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('No network')), patch('app.llm.client.OllamaClient.call_model', return_value=json.dumps(self.draft())) as model:
                result, failed = process_chat_message(ChatRequest(project_id='transition', dataset_id='olist.db::orders', message='For those same delivered orders purchased in 2018, calculate late delivery percentage. No chart.'), db, lambda _: None)
            self.assertFalse(failed, result['content'])
            self.assertEqual(model.call_count, 1)
            audit = result['results']['comparison_audit']
            self.assertEqual((audit['comparable_count'], audit['matched_count'], audit['missing_actual_count'], audit['missing_comparison_count']), (52777, 4078, 6, 0))
            self.assertAlmostEqual(audit['percentage'], 7.726850711484169)
            self.assertEqual(result['analysis_package']['charts'], [])
            self.assertEqual(json.loads(db.get(DBChatHistory, REF).metadata_json), metadata)
        engine.dispose()
