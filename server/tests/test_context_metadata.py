import copy,json,unittest
from pathlib import Path
from app.analysis.operations import guard_repair,validate_plan
from app.services.output_identity import planner_history,resolve_outputs,OutputIdentityError
ROOT=Path(__file__).parent/'fixtures'
CAP=json.loads((ROOT/'single_output_followup_failure.json').read_text())

class ContextMetadata(unittest.TestCase):
 def history(self):
  return {'recent_successes':[{'message_id':CAP['reference'],'analysis':{'plan':CAP['baseline']}},{'message_id':'another-stored-id','analysis':{'plan':CAP['baseline']}}]}
 def test_short_handles_roundtrip_without_mutating_stored_history(self):
  history=self.history();original=copy.deepcopy(history)
  self.assertEqual([e['message_id'] for e in planner_history(history)['recent_successes']],['success_1','success_2'])
  for handle,real in [('success_1',CAP['reference']),('success_2','another-stored-id')]:
   draft=copy.deepcopy(CAP['draft']);draft['reference_message_id']=handle
   resolved=resolve_outputs(draft,history)
   self.assertEqual(resolved['reference_message_id'],real)
   self.assertEqual(resolved['analysis_plan']['outputs'][0]['id'],CAP['baseline']['outputs'][0]['id'])
  self.assertEqual(history,original)
 def test_unknown_and_colliding_handles_do_not_guess(self):
  h=self.history();d=copy.deepcopy(CAP['draft']);d['reference_message_id']='success_99'
  with self.assertRaises(OutputIdentityError):resolve_outputs(d,h)
  h['recent_successes'][1]['message_id']='success_1';d['reference_message_id']='success_1'
  with self.assertRaises(OutputIdentityError):resolve_outputs(d,h)
 def test_envelope_presentation_moves_without_changing_meaning(self):
  diagnostics=json.loads((ROOT/'envelope_presentation_repair.json').read_text())
  bad,good=[d['output'] for d in diagnostics]
  guard_repair(bad,good)
  changed=copy.deepcopy(good);changed['analysis_plan']['chart_scope']['preference']='automatic'
  with self.assertRaises(ValueError):guard_repair(bad,changed)
  conflict=copy.deepcopy(bad);conflict['analysis_plan']['chart_scope']={'preference':'required'}
  with self.assertRaises(ValueError):guard_repair(conflict,good)
  changed=copy.deepcopy(good);changed['analysis_plan']['outputs'][0]['parameters']['columns']=['product_height_cm']
  with self.assertRaises(ValueError):guard_repair(bad,changed)
