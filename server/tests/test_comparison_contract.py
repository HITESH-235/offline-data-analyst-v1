import copy,json,sqlite3,unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.analysis.comparison_summary import normalize_parameters,calculate,contract_instructions
from app.llm.agent import _tool_fingerprint,_execute_tool
from app.llm.prompts import SIMPLE_TOOLS_PROMPT
from app.api.v1.chat import process_chat_message
from app.api.v1.projects import list_saved_analyses
from app.models.chat import ChatRequest
from app.models.project import DBProject
from app.storage.sqlite.session import Base
from app.services.dataset_manager import DatasetManager

CAPTURE=json.loads((Path(__file__).parent/'fixtures/comparison_summary_live.json').read_text())

class ComparisonContractTest(unittest.TestCase):
 def setUp(self):
  self.engine=create_engine('sqlite://');Base.metadata.create_all(self.engine);self.db=Session(self.engine)
  self.db.add(DBProject(id='test',name='Test'));self.db.commit()
 def tearDown(self):self.db.close();self.engine.dispose()
 def run_case(self,planner_selected,replies=None,initial=None):
  params=copy.deepcopy(initial if initial is not None else CAPTURE['parameters'])
  plan={'intent':'SIMPLE','context_action':'standalone','analysis_plan':{'source':{'tables':[CAPTURE['dataset_id']]},
        'outputs':[{'id':'comparison','kind':'comparison_summary','parameters':params}]}}
  from app.services import planned_analysis
  with patch('app.api.v1.chat.QueryPlanner.plan_query',return_value=plan),patch('app.llm.agent.Agent.run',side_effect=AssertionError('No alternate deterministic route')) as model,patch.object(planned_analysis,'execute',wraps=planned_analysis.execute) as execute:
   result,failed=process_chat_message(ChatRequest(project_id='test',dataset_id=CAPTURE['dataset_id'],message=CAPTURE['question']),self.db,lambda stage:None)
  return result,failed,model,execute
 def action(self,p):return json.dumps({'action':'tool_call','tool':'comparison_summary','parameters':p})
 def assert_result(self,result):
  audit=result['results']['comparison_audit']
  self.assertEqual((audit['filtered_count'],audit['missing_actual_count'],audit['eligible_count'],audit['comparable_count'],audit['missing_comparison_count'],audit['matched_count']),(96478,8,96470,96470,0,6534))
  self.assertAlmostEqual(audit['percentage'],6.7730900798175595)
  filters=audit['parameters']['eligibility_filters']
  self.assertEqual(filters,[{'column':'order_status','operator':'==','value':'delivered'}])
  self.assertNotIn('filters',audit['parameters'])
  with sqlite3.connect(DatasetManager.get_dataset(None,CAPTURE['dataset_id']).filepath) as db:
   expected=db.execute("SELECT COUNT(*),SUM(date(order_delivered_customer_date)>date(order_estimated_delivery_date)) FROM orders WHERE order_status='delivered' AND order_delivered_customer_date IS NOT NULL AND order_estimated_delivery_date IS NOT NULL").fetchone()
  self.assertEqual((audit['comparable_count'],audit['matched_count']),expected)
  self.assertIn('6.773090%',result['content'])
  saved=next(s for s in list_saved_analyses('test',self.db) if s['id']==result['id'])
  self.assertEqual(saved['result'],result['results'])
 def test_exact_captured_call_both_live_dispatch_paths(self):
  for direct in (True,False):
   with self.subTest(planner_selected=direct):
    result,failed,model,execute=self.run_case(direct)
    self.assertFalse(failed,result);self.assertEqual(execute.call_count,1)
    model.assert_not_called()
    self.assert_result(result)
 def test_invalid_plan_has_no_agent_retry_or_substitution(self):
  invalid={**CAPTURE['parameters'],'unrecognized':True}
  result,failed,model,execute=self.run_case(True,initial=invalid)
  self.assertTrue(failed);model.assert_not_called();execute.assert_not_called();self.assertNotIn('results',result)
 def test_bad_column_executes_once_without_agent_fallback(self):
  invalid={**CAPTURE['parameters'],'value_column':'missing_column'}
  result,failed,model,execute=self.run_case(True,initial=invalid)
  self.assertTrue(failed);model.assert_not_called();self.assertEqual(execute.call_count,0)
  self.assertNotIn('results',result)
 def test_invalid_planned_call_cannot_finalize_unrelated_result(self):
  invalid={**CAPTURE['parameters'],'unknown':1}
  final=json.dumps({'action':'final_answer','content':'Delivered count is enough; completed.'})
  unrelated=json.dumps({'action':'tool_call','tool':'aggregation','parameters':{'group_by':['order_status'],'aggregations':{'order_id':'count'}}})
  for replies in [[final],[unrelated,final]]:
   result,failed,model,execute=self.run_case(True,replies,invalid)
   self.assertTrue(failed);self.assertNotIn('results',result)
 def test_selected_comparison_cannot_be_replaced_even_without_percentage_keyword(self):
  invalid={**CAPTURE['parameters'],'unknown':1}
  unrelated=json.dumps({'action':'tool_call','tool':'aggregation','parameters':{'group_by':['order_status'],'aggregations':{'order_id':'count'}}})
  with patch.dict(CAPTURE,{'question':'Compare the delivery dates.'}):
   result,failed,model,execute=self.run_case(True,[unrelated,json.dumps({'action':'final_answer','content':'Completed'})],invalid)
  self.assertTrue(failed);self.assertNotIn('results',result)
 def test_shared_contract_alias_conflicts_and_population_validation(self):
  text=contract_instructions();self.assertIn(text,SIMPLE_TOOLS_PROMPT)
  normalized=normalize_parameters(CAPTURE['parameters'])
  self.assertEqual(_tool_fingerprint('comparison_summary',CAPTURE['parameters']),_tool_fingerprint('comparison_summary',normalized))
  for bad in [{**CAPTURE['parameters'],'filters':[]},{**CAPTURE['parameters'],'surprise':0},{**CAPTURE['parameters'],'eligibility_filters':None},{**CAPTURE['parameters'],'eligibility_filters':[{'column':'order_status','operator':'==','value':'delivered','unknown':True}]}]:
   with self.assertRaises(ValueError):normalize_parameters(bad)
  invalid={**CAPTURE['parameters'],'eligibility_filters':[{'column':'missing','operator':'==','value':'delivered'}]}
  frame=pd.DataFrame({'order_delivered_customer_date':['2020-01-01 23:59:59','2020-01-02',None,'2020-01-01'], 'order_estimated_delivery_date':['2020-01-01','2020-01-01','2020-01-01',None], 'order_status':['delivered']*4})
  with self.assertRaises(ValueError):calculate(frame,invalid)
  facts=calculate(frame,CAPTURE['parameters'])['comparison_audit']
  self.assertEqual((facts['matched_count'],facts['comparable_count'],facts['missing_actual_count'],facts['missing_comparison_count']),(1,2,1,1))

if __name__=='__main__':unittest.main()
