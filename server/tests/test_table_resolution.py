import copy,json,sqlite3,unittest
import pandas as pd
from app.analysis.calendar import calculate
from unittest.mock import patch
from app.llm.table_selector import TableSelector
from app.llm.agent import Agent
from app.llm.planner import QueryPlanner
from app.services.metadata_service import MetadataService
from app.services.dataset_manager import DatasetManager

CATALOG={'olist.db::orders':{},'olist.db::order_financials':{},'northwind.db::Orders':{},'northwind.db::Products':{}}
SOURCE={'tables':['order_financials','orders'],'join_keys':[{'from_table':'order_financials','from_column':'order_id','to_table':'orders','to_column':'order_id'}]}
QUESTION='Join order_financials with orders on order_id. Calculate monthly paid totals for 2017 using order_purchase_timestamp. Sum payment_total_cents, divide by 100, and label the results Paid Total (BRL). Show a chronological line chart.'

class TableResolutionTest(unittest.TestCase):
 def test_bare_names_and_endpoints_resolve_in_active_database(self):
  original={'tables_needed':SOURCE['tables'],'join_keys':SOURCE['join_keys']};before=copy.deepcopy(original)
  result=TableSelector.resolve_selection(original,CATALOG,'olist.db::order_financials')
  self.assertEqual(result['tables_needed'],['olist.db::order_financials','olist.db::orders'])
  self.assertEqual(result['join_keys'][0]['to_table'],'olist.db::orders')
  self.assertEqual(original,before)
  TableSelector.validate_selection(result,CATALOG)
 def test_unknown_ambiguous_and_explicit_ids_are_not_redirected(self):
  for names,active in [(['orders'],'file.csv'),(['missing'],'olist.db::orders'),(['absent.db::orders'],'olist.db::orders')]:
   with self.assertRaises(ValueError):TableSelector.resolve_selection({'tables_needed':names},CATALOG,active)
  ambiguous={**CATALOG,'olist.db::Orders':{}}
  with self.assertRaisesRegex(ValueError,'unambiguously'):
   TableSelector.resolve_selection({'tables_needed':['ORDERS']},ambiguous,'olist.db::order_financials')
  result=TableSelector.resolve_selection({'tables_needed':['northwind.db::Orders','order_financials']},CATALOG,'olist.db::orders')
  self.assertEqual(result['tables_needed'],['northwind.db::Orders','olist.db::order_financials'])
  with self.assertRaisesRegex(ValueError,'same SQLite database'):DatasetManager.load_joined_dataframe(result['tables_needed'],[])
 def test_planner_receives_actual_catalog_ids_and_relationships(self):
  with patch('app.llm.planner.OllamaClient.call_model',return_value=json.dumps({'intent':'SIMPLE'})) as model:
   QueryPlanner.plan_query(QUESTION,{'dataset_id':'olist.db::order_financials','columns':['order_id','payment_total_cents']})
  prompt=model.call_args.kwargs['prompt']
  self.assertIn('AUTHORITATIVE SOURCE CATALOG',prompt)
  self.assertIn('olist.db::orders',prompt);self.assertIn('order_purchase_timestamp',prompt)
  self.assertIn('olist.db::order_financials',prompt)
  self.assertIn('never a real database',prompt)
 def test_both_table_selection_entry_points(self):
  actual=MetadataService.get_catalog_index()
  selection={'tables_needed':SOURCE['tables'],'join_keys':SOURCE['join_keys']}
  with patch('app.llm.table_selector.OllamaClient.call_model',return_value=json.dumps(selection)):
   agent_selected=TableSelector.select_tables(QUESTION,'olist.db::order_financials')
  with patch('app.llm.table_selector.OllamaClient.call_model') as model:
   planner_selected=TableSelector.select_tables(QUESTION,'olist.db::order_financials',resolved_source=SOURCE)
  model.assert_not_called();self.assertEqual(agent_selected,planner_selected)
 def test_metric_validation_is_scoped_but_missing_values_are_not_silently_dropped(self):
  frame=pd.DataFrame({'date':['2016-01-01','2017-01-01'],'paid':[None,100.]})
  state={'date_column':'date','years':[2017],'grain':'month','metric':{'name':'Paid','aggregation':'sum','expression':{'column':'paid'}}}
  result=calculate(frame,state);self.assertEqual(result['data'][0]['Paid'],100.)
  with self.assertRaisesRegex(ValueError,'missing or non-finite'):
   calculate(frame,{**state,'years':[2016]})
 def test_actual_monthly_calculation_with_bare_planner_source(self):
  state={'source':SOURCE,'metric':{'name':'Paid Total (BRL)','aggregation':'sum','expression':{'op':'multiply','args':[{'column':'payment_total_cents'},{'value':.01}]}},'date_column':'order_purchase_timestamp','years':[2017],'grain':'month','compare':False,'filters':[],'output':{'table':True,'chart':'line'}}
  # Missing payments are unknown, not zero; the known absent-payment order is in 2016.
  with patch('app.llm.agent.OllamaClient.call_model_chat') as model:
   response=Agent.run(QUESTION,'SIMPLE',{},'olist.db::order_financials',resolved_analysis=state)
  self.assertFalse(response.get('failed',False),response);model.assert_not_called()
  self.assertEqual(response['results']['row_count'],12)
  self.assertEqual(response['analysis_context']['source']['tables'],['olist.db::order_financials','olist.db::orders'])
  with sqlite3.connect(DatasetManager.get_dataset(None,'olist.db::orders').filepath) as db:
   expected=db.execute("SELECT strftime('%Y-%m',o.order_purchase_timestamp),SUM(f.payment_total_cents)/100.0 FROM order_financials f JOIN orders o ON f.order_id=o.order_id WHERE strftime('%Y',o.order_purchase_timestamp)='2017' GROUP BY 1 ORDER BY 1").fetchall()
  for row,(month,total) in zip(response['results']['data'],expected):
   self.assertEqual(row['Month'],month);self.assertAlmostEqual(row['Paid Total (BRL)'],total,places=5)

if __name__=='__main__':unittest.main()
