import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.analysis.operations import validate_plan, planner_instructions, guard_repair, ContractError
from app.api.v1.chat import process_chat_message
from app.models.chat import ChatRequest
from app.models.project import DBProject
from app.storage.sqlite.session import Base

CAPTURE=json.loads((Path(__file__).parent/'fixtures/comparison_measure_descriptor_observation.json').read_text())
QUESTION=json.loads((Path(__file__).parent/'fixtures/grouped_comparison_reduced_response.json').read_text())['question']
MEASURES=[{'operation':'comparable_count','output':'Comparable Orders'},
          {'operation':'matched_count','output':'Late Orders'},
          {'operation':'percentage','output':'Late Percentage','unit':'%'},
          {'operation':'missing_actual_count','output':'Missing Actual Date'},
          {'operation':'missing_comparison_count','output':'Missing Estimated Date'}]

def corrected():
    plan=copy.deepcopy(CAPTURE['planner_output'])
    plan['request_requirements']['outputs'][0]['measures']=copy.deepcopy(MEASURES)
    return plan

class ComparisonMeasureRequirementsTest(unittest.TestCase):
    def test_captured_operation_wide_descriptor_expands_to_every_native_measure(self):
        plan=validate_plan(CAPTURE['planner_output'])
        self.assertNotIn('request_requirements',plan)
        for extra in ({'source_column':'unrelated'},{'unit':'USD'},{'derived':{'column':'other'}}):
            bad=copy.deepcopy(CAPTURE['planner_output']);bad['request_requirements']['outputs'][0]['measures'][0].update(extra)
            with self.subTest(extra=extra),self.assertRaises(ContractError):validate_plan(bad)
    def test_schema_advertises_atomic_comparison_measures_and_typed_parameters(self):
        schema=json.loads(planner_instructions().split('Envelope schema:\n',1)[1])
        self.assertEqual(schema['allOf'][0]['then']['properties']['request_requirements'],{'type':'null'})
        self.assertIn('Parameters_comparison_summary',schema['$defs'])
    def test_one_repair_can_correct_representation_but_not_population_formula_or_sources(self):
        good=corrected();validate_plan(good);guard_repair(CAPTURE['planner_output'],good)
        for key,value in [('operator','>='),('eligibility_filters',[]),('sort_by','matched_count'),('group_by',[])]:
            bad=copy.deepcopy(good);bad['analysis_plan']['outputs'][0]['parameters'][key]=value
            with self.subTest(key=key),self.assertRaises(ContractError):guard_repair(CAPTURE['planner_output'],bad)
    def test_scalar_and_other_measure_labels_use_semantics_not_olist_strings(self):
        plan=corrected();p=plan['analysis_plan']['outputs'][0]['parameters']
        p.update(matched_label='Above target',count_label='Cases',comparison_label='Expected')
        plan['request_requirements']['outputs'][0]['parameters']=copy.deepcopy(p)
        plan['request_requirements']['outputs'][0]['measures']=[{'operation':'percentage','output':'Above target Percentage'}]
        validate_plan(plan)

class ComparisonMeasureReplayTest(unittest.TestCase):
    def setUp(self):
        self.engine=create_engine('sqlite://');Base.metadata.create_all(self.engine);self.db=Session(self.engine)
        self.db.add(DBProject(id='test',name='Test'));self.db.commit()
    def tearDown(self):self.db.close();self.engine.dispose()
    def send(self,replies):
        with patch('app.llm.client.OllamaClient.call_model',side_effect=[json.dumps(p) for p in replies]) as provider,patch('app.llm.agent.OllamaClient.call_model_chat') as interpreter:
            r,failed=process_chat_message(ChatRequest(project_id='test',dataset_id='olist.db::orders',message=QUESTION),self.db,lambda stage:None)
        interpreter.assert_not_called()
        return r,failed,provider.call_count
    def test_correct_atomic_requirements_complete_all_measures_in_one_call(self):
        r,failed,count=self.send([corrected()]);self.assertFalse(failed,r['content']);self.assertEqual(count,1)
        self.assertEqual(r['results']['row_count'],27)
        self.assertTrue(all(c['status']=='passed' for c in r['analysis_package']['completion_checks']))
        self.assertIn('6.773090%',r['content']);self.assertIn('**AL:** 21.410579%',r['content'])
        self.assertEqual(r['analysis_package']['charts'][0]['specification']['y'],'Late Percentage')
    def test_exact_capture_completes_without_repair_or_dropped_measures(self):
        r,failed,count=self.send([CAPTURE['planner_output']])
        self.assertFalse(failed,r['content']);self.assertEqual(count,1)
        self.assertEqual([d['accepted'] for d in r['planner_diagnostics']],[True])
        self.assertEqual(r['analysis_status'],'complete');self.assertEqual(r['results']['row_count'],27)
    def test_real_computational_disagreement_is_not_silently_ignored(self):
        bad=corrected();bad['request_requirements']['outputs'][0]['parameters']['operator']='>='
        r,failed,count=self.send([bad,bad]);self.assertTrue(failed);self.assertNotEqual(r.get('analysis_status'),'complete')
        self.assertNotIn('results',r)
