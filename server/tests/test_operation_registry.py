"""Full-route replay and negative coverage for the unified operation contract."""
import copy,json,sqlite3,unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.analysis.operations import validate,execute,matches,validate_plan,guard_repair,ContractError,planner_instructions
from app.api.v1.chat import process_chat_message
from app.api.v1.projects import list_saved_analyses,list_project_messages
from app.llm.planner import QueryPlanner
from app.models.chat import ChatRequest,DBChatHistory
from app.models.project import DBProject
from app.storage.sqlite.session import Base
from app.services.dataset_manager import DatasetManager
from app.services.analysis_context import load_context
from app.services.analysis_package import finalize,OutputAccumulator
from app.services.planned_analysis import validate_context

CAPTURES=json.loads((Path(__file__).parent/'fixtures/live_contract_failures.json').read_text())
MISPLACED=json.loads((Path(__file__).parent/'fixtures/misplaced_calendar_scope_observation.json').read_text())
class RegistryTest(unittest.TestCase):
 def setUp(self):
  self.engine=create_engine('sqlite://');Base.metadata.create_all(self.engine);self.db=Session(self.engine)
  self.db.add(DBProject(id='eval',name='Evaluation'));self.db.commit()
 def tearDown(self):self.db.close();self.engine.dispose()
 def send(self,question,dataset,plan,replies=(),selection=None,planner_replies=()):
  if plan.get('context_action')=='inherit' and not plan.get('reference_message_id'):
   entries=load_context(self.db,'eval')['recent_successes']
   if entries:
    prior=entries[0];plan=copy.deepcopy(plan);plan['reference_message_id']=prior['message_id']
    old=prior['analysis']['plan']['outputs'][0]['parameters'];new=plan['analysis_plan']['outputs'][0]['parameters']
    if not plan.get('changed_fields'):plan['changed_fields']=[k for k in ('grain','years','compare') if new.get(k)!=old.get(k)]
  route=[json.dumps(plan)]+[json.dumps(p) for p in planner_replies]+([json.dumps(selection)] if selection else [])
  diagnostics=[]
  with patch('app.llm.client.OllamaClient.call_model',side_effect=route) as planner,patch('app.llm.agent.OllamaClient.call_model_chat',side_effect=list(replies)) as agent:
   response,failed=process_chat_message(ChatRequest(project_id='eval',dataset_id=dataset,message=question),self.db,lambda stage:None)
  self.db.close();self.db=Session(self.engine)
  saved=next((s for s in list_saved_analyses('eval',self.db) if s['id']==response['id']),None)
  stored=json.loads(self.db.get(DBChatHistory,response['id']).metadata_json)
  self.assertEqual(stored.get('analysis_package'),response.get('analysis_package'))
  if saved:self.assertEqual(saved['analysisPackage'],response['analysis_package'])
  return response,failed,planner,agent,saved
 def action(self,step):return json.dumps({'action':'tool_call','tool':step['tool'],'parameters':step['parameters']})
 def test_actual_quarterly_capture_accepts_equivalent_calendar_contract(self):
  c=CAPTURES[1];state=c['steps'][0]['parameters']
  r,failed,planner,agent,saved=self.send(c['question'],'northwind.db::Orders',{'intent':'SIMPLE','context_action':'standalone','analysis_plan':{'source':state['source'],'outputs':[{'id':'quarterly_net_sales','kind':'calendar_aggregate','parameters':state}]}})
  self.assertFalse(failed,r);agent.assert_not_called();self.assertEqual(r['results']['row_count'],4)
  with sqlite3.connect(DatasetManager.get_dataset(None,'northwind.db::Orders').filepath) as db:
   expected=db.execute('''SELECT (CAST(strftime('%m',o.OrderDate) AS INT)+2)/3,SUM(d.UnitPrice*d.Quantity*(1-d.Discount)) FROM Orders o JOIN "Order Details" d ON o.OrderID=d.OrderID WHERE strftime('%Y',o.OrderDate)='2021' GROUP BY 1 ORDER BY 1''').fetchall()
  for row,(_,value) in zip(r['results']['data'],expected):self.assertAlmostEqual(row['Net Sales'],value,places=5)
 def test_actual_coverage_capture_binds_group_rows_to_named_populations(self):
  c=CAPTURES[2]
  source={'tables':['olist.db::order_financials'],'join_keys':[]}
  outputs=[{'id':spec['id'],'kind':'aggregation','parameters':{'group_by':[], 'aggregations':{'order_id':'count'},'filters':spec.get('filters',[]),'output_names':{'order_id':spec['measures'][0]['output']}}} for spec in c['contract']['outputs']]
  r,failed,_,_,saved=self.send(c['question'],'olist.db::order_financials',{'intent':'SIMPLE','analysis_plan':{'source':source,'outputs':outputs}})
  self.assertFalse(failed,r['content']);tables=r['analysis_package']['tables'];self.assertEqual(len(tables),3)
  with sqlite3.connect(DatasetManager.get_dataset(None,'olist.db::order_financials').filepath) as db:expected=db.execute('SELECT COUNT(*),SUM(has_payments),COUNT(*)-SUM(has_payments) FROM order_financials').fetchone()
  self.assertEqual([next(iter(t['result']['data'][0].values())) for t in tables],list(expected))
  self.assertTrue(all(t['completion_status']=='complete' for t in tables))
 def test_distinct_is_executed_and_verifies_all_countries(self):
  plan={'intent':'SIMPLE','context_action':'standalone','analysis_plan':{'source':{'tables':['northwind.db::Orders']},'outputs':[{'id':'customers','kind':'aggregation','parameters':{'group_by':['ShipCountry'],'aggregations':{'CustomerID':'count_distinct'},'output_names':{'CustomerID':'Distinct Customer Count'},'sort_by':'Distinct Customer Count','ascending':False}}]}}
  r,failed,_,agent,_=self.send(CAPTURES[0]['question'],'northwind.db::Orders',plan)
  self.assertFalse(failed,r);agent.assert_not_called()
  with sqlite3.connect(DatasetManager.get_dataset(None,'northwind.db::Orders').filepath) as db:expected=dict(db.execute('SELECT ShipCountry,COUNT(DISTINCT CustomerID) FROM Orders GROUP BY ShipCountry'))
  self.assertEqual({row['ShipCountry']:row['Distinct Customer Count'] for row in r['results']['data']},expected)
 def test_distinct_downgrade_is_not_exposed_even_as_partial(self):
  c=CAPTURES[0];wrong=c['steps'][1]
  r,failed,*_=self.send(c['question'],'northwind.db::Orders',{'intent':'SIMPLE','context_action':'standalone'},[self.action(wrong),json.dumps({'action':'final_answer','content':'distinct counts done'})],{'tables_needed':['northwind.db::Orders']})
  self.assertTrue(failed);self.assertNotIn('results',r);self.assertEqual(r['analysis_package']['tables'],[])
 def test_empty_filters_equal_omission_real_filters_preserved(self):
  frame=pd.DataFrame({'group':['a','a','b'],'id':[1,1,2]});p={'group_by':['group'],'aggregations':{'id':'count_distinct'}}
  a=execute('aggregation',p,frame);b=execute('aggregation',{**p,'filters':[]},frame)
  self.assertEqual(a,b)
  subset={**p,'filters':[{'column':'group','operator':'==','value':'b'}]}
  result=execute('aggregation',subset,frame);self.assertEqual(result['row_count'],1);self.assertFalse(matches('aggregation',p,result))
 def test_distinct_labels_cannot_disguise_ordinary_counts(self):
  frame=pd.DataFrame({'id':[1,1,2]})
  for label in ['Distinct Customers','distinct_customers','DistinctCustomers','Distinct Customer Count']:
   p={'aggregations':{'id':'count'},'output_names':{'id':label}}
   ordinary=execute('aggregation',p,frame)
   self.assertEqual(ordinary['data'][0][label],3)
   # Display text never supplies count_distinct semantics.
   self.assertEqual(ordinary['measure_provenance'][label]['operation'],'count')
   p['aggregations']['id']='count_distinct'
   self.assertEqual(execute('aggregation',p,frame)['data'][0][label],2)
 def test_schema_paths_and_one_repair_with_diagnostics(self):
  bad={'intent':'SIMPLE','context_action':'standalone','analysis_plan':{'source':{'tables':['northwind.db::Orders']},'outputs':[{'id':'bad','kind':'aggregation','parameters':{'group_by':[],'aggregations':{'OrderID':'count'},'invented':'sk-or-v1-'+('a'*64)}}]}}
  good=copy.deepcopy(bad);del good['analysis_plan']['outputs'][0]['parameters']['invented']
  diagnostics=[]
  with patch('app.llm.client.OllamaClient.call_model',side_effect=[json.dumps(bad),json.dumps(good)]) as model:
   result=QueryPlanner.plan_query('Count orders.',{'columns':['OrderID']},diagnostics=diagnostics)
  self.assertEqual(model.call_count,2);self.assertEqual(len(diagnostics),2)
  self.assertIn('$.analysis_plan.outputs[0].parameters.invented',diagnostics[0]['error'])
  self.assertNotIn('sk-or-v1-',json.dumps(diagnostics));self.assertIn('invented',model.call_args.kwargs['prompt'])
 def test_schema_repair_cannot_downgrade_distinct(self):
  original={'intent':'SIMPLE','analysis_plan':{'source':{'tables':['northwind.db::Orders']},'outputs':[{'id':'x','kind':'aggregation','parameters':{'group_by':[],'aggregations':{'CustomerID':'count_distinct'},'extra':True}}]}}
  repaired=copy.deepcopy(original);del repaired['analysis_plan']['outputs'][0]['parameters']['extra'];repaired['analysis_plan']['outputs'][0]['parameters']['aggregations']['CustomerID']='count'
  diagnostics=[]
  with patch('app.llm.client.OllamaClient.call_model',side_effect=[json.dumps(original),json.dumps(repaired)]) as model,self.assertRaisesRegex(ValueError,'changed'):
   QueryPlanner.plan_query('Count distinct customers.',{'columns':['CustomerID']},diagnostics=diagnostics)
  self.assertEqual(model.call_count,2);self.assertFalse(diagnostics[-1]['accepted'])
 def test_tampered_values_formula_units_scope_fail_publication(self):
  frame=pd.DataFrame({'name':['a','b'],'cents':[100,200]});p={'group_by':['name'],'aggregations':{'cents':'sum'},'transforms':[{'column':'cents','divide_by':100,'as':'Amount','unit':'BRL'}]}
  result=execute('aggregation',p,frame)
  for change in ['data','units','parameters']:
   bad=copy.deepcopy(result);target=copy.deepcopy(p)
   if change=='data':bad['data'][0]['Amount']=999
   elif change=='units':bad['units']['Amount']='USD'
   else:target['filters']=[{'column':'name','operator':'==','value':'b'}]
   a=OutputAccumulator()
   if change!='parameters':
    with self.assertRaisesRegex(ValueError,'evidence'):a.record('aggregation',p,bad,{'tables':['fixture']},0,'amount')
    continue
   a.record('aggregation',p,bad,{'tables':['fixture']},0,'amount')
   pub=finalize({'analysis_outputs':a.export()},'amount','eval','id',{'outputs':[{'id':'amount','kind':'aggregation','parameters':target,'source_tables':['fixture']}]})
   self.assertNotEqual(pub['analysis_status'],'complete')
 def test_unsupported_calendar_metric_cannot_be_repaired_into_ordinary_count(self):
  state=copy.deepcopy(CAPTURES[1]['steps'][0]['parameters'])
  state['metric']={'name':'Distinct Customers','aggregation':'count_distinct','expression':{'column':'CustomerID'}}
  bad={'intent':'SIMPLE','context_action':'standalone','analysis_plan':{'source':state['source'],'outputs':[{'id':'customers','kind':'calendar_aggregate','parameters':state}]}}
  ordinary=copy.deepcopy(bad);ordinary['analysis_plan']['outputs'][0]['parameters']['metric']['aggregation']='count'
  with patch('app.llm.client.OllamaClient.call_model',side_effect=[json.dumps(bad),json.dumps(ordinary)]) as provider,self.assertRaisesRegex(ValueError,'changed requested measure'):
   QueryPlanner.plan_query('Calculate distinct customers per calendar quarter.',{'columns':['CustomerID','OrderDate']})
  self.assertEqual(provider.call_count,2)
 def test_comparison_year_invariant_and_failed_intent_separation(self):
  state=copy.deepcopy(CAPTURES[1]['steps'][0]['parameters']);state.update(years=[2021,2022],compare=True)
  good=validate('calendar_aggregate',state);bad={**good,'years':[2021]}
  with self.assertRaisesRegex(ValueError,'years'):validate('calendar_aggregate',bad)
  history={'recent_successes':[{'message_id':'last','analysis':{'version':1,'plan':{'source':state['source'],'outputs':[{'id':'calendar','kind':'calendar_aggregate','parameters':state}]}}}]}
  plan={'source':state['source'],'outputs':[{'id':'calendar','kind':'calendar_aggregate','parameters':{**state,'grain':'month'}}]}
  validate_context(plan,history,reference='last',changed_fields=['grain'])
  plan['outputs'][0]['parameters']['years']=[2022]
  with self.assertRaisesRegex(ValueError,'years'):validate_context(plan,history,reference='last',changed_fields=['grain'])
 def test_typed_comparison_sequence_reload_pending_failure_and_sql(self):
  state=copy.deepcopy(CAPTURES[1]['steps'][0]['parameters']);state['grain']='month'
  def plan(p,action='inherit',changed=()):
   return {'intent':'SIMPLE','context_action':action,'changed_fields':list(changed),'analysis_plan':{'source':p['source'],'outputs':[{'id':'sales','kind':'calendar_aggregate','parameters':p}],'chart_scope':{'required':True}}}
  first,failed,*_=self.send('Net sales by month for 2021.','northwind.db::Orders',plan(state,'standalone'));self.assertFalse(failed,first)
  quarter=copy.deepcopy(state);quarter['grain']='quarter'
  # Associative equivalent formula, not an exemption from formula checking.
  args=quarter['metric']['expression']['args']
  quarter['metric']['expression']={'op':'multiply','args':[{'op':'multiply','args':args[:2]},args[2]]}
  second,failed,*_=self.send('Regroup those sales quarterly.','northwind.db::Orders',plan(quarter));self.assertFalse(failed,second)
  comparison={**quarter,'compare':True,'years':[2021,2022]}
  third,failed,*_=self.send('Compare with 2022 and retain the previous year.','northwind.db::Orders',plan(comparison));self.assertFalse(failed,third)
  bad={**comparison,'date_column':'missing_timestamp'}
  failure,failed,*_=self.send('Try a different timestamp.','northwind.db::Orders',plan(bad,changed=['date_column']));self.assertTrue(failed)
  self.db.close();self.db=Session(self.engine)
  history=load_context(self.db,'eval');self.assertEqual(history['recent_successes'][0]['message_id'],third['id'])
  self.assertFalse(history['unresolved_request']['succeeded']);self.assertEqual(history['unresolved_request']['plan']['outputs'][0]['parameters']['years'],[2021,2022])
  monthly={**comparison,'grain':'month'}
  result,failed,*_=self.send('Show the same comparison monthly.','northwind.db::Orders',plan(monthly));self.assertFalse(failed,result)
  self.assertEqual(result['results']['row_count'],12);self.assertEqual(len(result['results']['calendar_chart']['series']),2)
  with sqlite3.connect(DatasetManager.get_dataset(None,'northwind.db::Orders').filepath) as db:
   expected=db.execute('''SELECT CAST(strftime('%Y',o.OrderDate) AS INT),CAST(strftime('%m',o.OrderDate) AS INT),SUM(d.UnitPrice*d.Quantity*(1-d.Discount)) FROM Orders o JOIN "Order Details" d ON o.OrderID=d.OrderID WHERE strftime('%Y',o.OrderDate) IN ('2021','2022') GROUP BY 1,2 ORDER BY 1,2''').fetchall()
  for year,month,value in expected:self.assertAlmostEqual(result['results']['data'][month-1][f'Net Sales {year}'],value,places=5)
 def test_wrong_calendar_formula_and_source_are_rejected(self):
  from app.services.request_requirements import validate_plan_request
  state=copy.deepcopy(CAPTURES[1]['steps'][0]['parameters'])
  requirement={'outputs':[{'id':'calendar','kind':'calendar_aggregate','parameters':state,'source_tables':state['source']['tables']}]}
  for key in ['formula','source']:
   bad=copy.deepcopy(state)
   if key=='formula':bad['metric']['expression']={'column':'Quantity'}
   source=bad['source'] if key=='formula' else {'tables':['northwind.db::Orders']}
   with self.assertRaises(ValueError):validate_plan_request({'intent':'SIMPLE','analysis_plan':{'source':source,'outputs':[{'id':'calendar','kind':'calendar_aggregate','parameters':bad}]}},requirement)
 def test_live_alias_reference_failure_repairs_before_execution(self):
  bad={'intent':'SIMPLE','context_action':'standalone','analysis_plan':{'source':{'tables':['olist.db::orders']},'outputs':[{'id':'count','kind':'aggregation','parameters':{'aggregations':{'order_id':'count_distinct'},'output_names':{'count_distinct_order_id':'Orders'}}}]}}
  good=copy.deepcopy(bad);good['analysis_plan']['outputs'][0]['parameters']['output_names']={'order_id':'Orders'}
  with patch('app.llm.client.OllamaClient.call_model',side_effect=[json.dumps(bad),json.dumps(good)]) as provider,patch('app.llm.agent.OllamaClient.call_model_chat') as agent:
   result,failed=process_chat_message(ChatRequest(project_id='eval',dataset_id='olist.db::orders',message='Count different order IDs.'),self.db,lambda stage:None)
  self.assertFalse(failed,result);self.assertEqual(provider.call_count,1);agent.assert_not_called()
  self.assertTrue(result['planner_diagnostics'][0]['accepted'])
  with sqlite3.connect(DatasetManager.get_dataset(None,'olist.db::orders').filepath) as db:expected=db.execute('SELECT COUNT(DISTINCT order_id) FROM orders').fetchone()[0]
  self.assertEqual(result['results']['data'][0]['Orders'],expected)
 def test_actual_new_diagnostic_alias_capture_repairs_and_all_outputs_match_sql(self):
  captured=json.loads((Path(__file__).parent/'fixtures/new_planner_alias_observation.json').read_text())
  bad=captured['plan'];good=copy.deepcopy(bad)
  for output in good['analysis_plan']['outputs']:
   if output['kind']=='aggregation':
    names=output['parameters'].get('output_names',{})
    if names:output['parameters']['output_names']={next(iter(output['parameters']['aggregations'])):next(iter(names.values()))}
  with patch('app.llm.client.OllamaClient.call_model',side_effect=[json.dumps(bad),json.dumps(good)]) as model:
   result,failed=process_chat_message(ChatRequest(project_id='eval',dataset_id='olist.db::orders',message=captured['question']),self.db,lambda stage:None)
  self.assertFalse(failed,result);self.assertEqual(model.call_count,1)
  tables=result['analysis_package']['tables'];self.assertEqual(len(tables),6)
  with sqlite3.connect(DatasetManager.get_dataset(None,'olist.db::orders').filepath) as db:
   expected=db.execute("SELECT COUNT(*),SUM(order_delivered_customer_date IS NULL),SUM(order_delivered_customer_date IS NOT NULL AND order_estimated_delivery_date IS NULL),SUM(order_delivered_customer_date IS NOT NULL AND order_estimated_delivery_date IS NOT NULL),SUM(date(order_delivered_customer_date)>date(order_estimated_delivery_date)) FROM orders WHERE order_status='delivered'").fetchone()
  self.assertEqual([next(iter(t['result']['data'][0].values())) for t in tables[:5]],list(expected))
  self.assertAlmostEqual(tables[-1]['result']['comparison_audit']['percentage'],100*expected[-1]/expected[-2])
  self.db.close();self.db=Session(self.engine)
  snapshot=next(s for s in list_saved_analyses('eval',self.db) if s['id']==result['id'])
  self.assertEqual(snapshot['analysisPackage'],result['analysis_package'])
 def test_new_literal_date_capture_executes_all_states_against_sql(self):
  capture=json.loads((Path(__file__).parent/'fixtures/new_literal_date_observation.json').read_text());plan=capture['diagnostics'][0]['output']
  result,failed,_,_,snapshot=self.send(capture['question'],'olist.db::order_financials',plan)
  self.assertFalse(failed,result)
  with sqlite3.connect(DatasetManager.get_dataset(None,'olist.db::orders').filepath) as db:
   expected=dict(db.execute("SELECT c.customer_state,SUM(f.payment_total_cents)/100.0 FROM order_financials f JOIN orders o ON f.order_id=o.order_id JOIN customers c ON o.customer_id=c.customer_id WHERE f.has_payments=1 AND date(o.order_purchase_timestamp)>='2018-01-01' AND date(o.order_purchase_timestamp)<'2019-01-01' GROUP BY c.customer_state"))
  actual={row['customer_state']:row['Paid Amount (BRL)'] for row in result['results']['data']}
  self.assertEqual(set(actual),set(expected))
  for state,value in expected.items():self.assertAlmostEqual(actual[state],value,places=5)
  self.assertEqual(snapshot['analysisPackage'],result['analysis_package'])
 def test_new_nullable_predicate_capture_preserves_actual_price_filter(self):
  capture=json.loads((Path(__file__).parent/'fixtures/new_nullable_predicate_observation.json').read_text())
  before=capture['diagnostics'][0]['output'];after=capture['diagnostics'][1]['output']
  a=validate_plan(before);b=validate_plan(after)
  self.assertEqual(a['analysis_plan']['outputs'][0]['parameters']['filters'],b['analysis_plan']['outputs'][0]['parameters']['filters'])
  guard_repair(before,b,'$.analysis_plan.outputs[0].parameters.filters[0]')
  result,failed,*_=self.send(capture['question'],'olist.db::order_items',before);self.assertFalse(failed,result)
  with sqlite3.connect(DatasetManager.get_dataset(None,'olist.db::orders').filepath) as db:
   expected=db.execute("SELECT s.seller_state,SUM(i.freight_value_cents)/100.0 FROM order_items i JOIN sellers s ON i.seller_id=s.seller_id WHERE i.price_cents>=10000 GROUP BY s.seller_state ORDER BY 2 DESC,1 LIMIT 5").fetchall()
  rows=result['results']['data'];self.assertEqual([(r['seller_state'],r['Freight (BRL)']) for r in rows],expected)
  dropped=copy.deepcopy(b);dropped['analysis_plan']['outputs'][0]['parameters'].pop('filters')
  with self.assertRaisesRegex(ValueError,'population'):guard_repair(before,dropped)
 def test_literal_calendar_day_and_timestamp_comparisons_differ(self):
  frame=pd.DataFrame({'date':['2017-09-01 23:59:59','2017-09-02 00:00:00',None]})
  p={'filters':[{'column':'date','operator':'>','value':'2017-09-01','value_type':'date','date_part':'date'}]}
  day=execute('filtering',p,frame);self.assertEqual(day['row_count'],1)
  p['filters'][0].pop('date_part');time=execute('filtering',p,frame);self.assertEqual(time['row_count'],2)
  self.assertEqual(execute('filtering',{'filters':[{'column':'date','operator':'==','value':None,'value_column':None}]},frame)['row_count'],1)
 def test_analytical_plans_cannot_bypass_publication_as_conversation(self):
  plan={'intent':'CONVERSATION','context_action':'standalone','analysis_plan':{'source':{'tables':['olist.db::orders']},'outputs':[{'id':'x','kind':'aggregation','parameters':{'aggregations':{'order_id':'count'}}}]}}
  with self.assertRaisesRegex(ValueError,'intent'):validate_plan(plan)
  plan['intent']='SIMPLE';plan['unsupported_reason']='Only an approximation is available.'
  with self.assertRaisesRegex(ValueError,'unsupported_reason'):validate_plan(plan)
 def test_actual_formula_wrapper_repair_executes_and_reopens(self):
  c=json.loads((Path(__file__).parent/'fixtures/new_formula_wrapper_observation.json').read_text())
  bad,good=[d['output'] for d in c['diagnostics']]
  r,failed,provider,agent,saved=self.send(c['question'],'northwind.db::Orders',bad,planner_replies=[good])
  self.assertFalse(failed,r);self.assertEqual(provider.call_count,2);agent.assert_not_called();self.assertIsNotNone(saved)
  diagnostic=r['planner_diagnostics'][0]
  self.assertIn('.metric.expression.args[1].args[0].constant',diagnostic['error'])
  self.assertNotIn('.Column.',diagnostic['error']);self.assertNotIn('.Expression.',diagnostic['error'])
  with sqlite3.connect(DatasetManager.get_dataset(None,'northwind.db::Orders').filepath) as db:
   expected=db.execute('''SELECT CAST(strftime('%m',o.OrderDate) AS INT),SUM(d.UnitPrice*d.Quantity*(1-d.Discount)) FROM Orders o JOIN "Order Details" d ON o.OrderID=d.OrderID WHERE strftime('%Y',o.OrderDate)='2021' GROUP BY 1 ORDER BY 1''').fetchall()
  self.assertEqual(len(r['results']['data']),len(expected))
  for row,(_,value) in zip(r['results']['data'],expected):self.assertAlmostEqual(row['Net Sales'],value,places=5)
 def test_formula_repair_preserves_constants_columns_and_join_predicates(self):
  c=json.loads((Path(__file__).parent/'fixtures/new_formula_wrapper_observation.json').read_text())
  bad,good=[d['output'] for d in c['diagnostics']]
  guard_repair(bad,validate_plan(good))
  for field in ['constant','column','join']:
   wrong=copy.deepcopy(good);expr=wrong['analysis_plan']['outputs'][0]['parameters']['metric']['expression']
   if field=='constant':expr['args'][1]['args'][0]['value']=2
   elif field=='column':expr['args'][1]['args'][1]['column']='Quantity'
   else:wrong['analysis_plan']['source']['join_keys'][0]['from_column']='Freight'
   with self.assertRaisesRegex(ValueError,'changed'):guard_repair(bad,validate_plan(wrong))
  # Arbitrary wrappers do not acquire execution meaning from a repair.
  opaque=copy.deepcopy(bad)
  opaque['analysis_plan']['outputs'][0]['parameters']['metric']['expression']['args'][1]['args'][0]={'unknown':{'value':1}}
  with self.assertRaisesRegex(ValueError,'changed'):guard_repair(opaque,validate_plan(good))
 def test_schema_repair_budget_is_exactly_one(self):
  diagnostics=[]
  with patch('app.llm.client.OllamaClient.call_model',return_value='not JSON') as model,self.assertRaisesRegex(ValueError,'one attempt'):
   QueryPlanner.plan_query('Compute an analysis.',{'columns':[]},diagnostics=diagnostics)
  self.assertEqual(model.call_count,2);self.assertEqual(len(diagnostics),2)
 def seed_captured_monthly_context(self):
  seed=MISPLACED['seed']
  # Keep both captured planner payloads byte-for-byte structurally identical:
  # create their exact referenced assistant ID through the normal save path.
  with patch('app.api.v1.chat.uuid.uuid4',side_effect=['captured-monthly-user',seed['message_id']]):
   response,failed,*_=self.send(seed['question'],'northwind.db::Orders',seed['plan'])
  self.assertFalse(failed,response);self.assertEqual(response['id'],seed['message_id'])
  return response
 def test_captured_single_output_rename_binds_and_schema_repair_reopens(self):
  seed=self.seed_captured_monthly_context()
  bad,good=[copy.deepcopy(d['output']) for d in MISPLACED['diagnostics']]
  # A single stored output has one owner even when the planner changes its label.
  # Keep the captured drafts unchanged; the system must retain that identity.
  with self.assertRaisesRegex(ValueError,'chart_scope'):validate_plan(bad)
  result,failed,provider,agent,saved=self.send(MISPLACED['question'],'northwind.db::Orders',bad,planner_replies=[good])
  self.assertFalse(failed,result);self.assertEqual(provider.call_count,2);agent.assert_not_called()
  self.assertEqual(result['analysis_plan']['outputs'][0]['id'],seed['analysis_plan']['outputs'][0]['id'])
  self.assertEqual(result['analysis_status'],'complete');self.assertIsNotNone(saved)
  self.assertEqual(result['results']['row_count'],4)
  self.assertEqual([d['accepted'] for d in result['planner_diagnostics']],[False,True])
  self.assertEqual(result['planner_diagnostics'][0]['output'],bad)
  self.assertIn(MISPLACED['diagnostics'][0]['error'],provider.call_args.kwargs['prompt'])
  with sqlite3.connect(DatasetManager.get_dataset(None,'northwind.db::Orders').filepath) as db:
   expected=db.execute('''SELECT (CAST(strftime('%m',o.OrderDate) AS INT)+2)/3,SUM(d.UnitPrice*d.Quantity*(1-d.Discount)) FROM Orders o JOIN "Order Details" d ON o.OrderID=d.OrderID WHERE strftime('%Y',o.OrderDate)='2021' GROUP BY 1 ORDER BY 1''').fetchall()
  for row,(_,value) in zip(result['results']['data'],expected):self.assertAlmostEqual(row['Net Sales'],value,places=5)
  self.assertEqual(saved['result'],result['results']);self.assertEqual(saved['analysisPackage'],result['analysis_package'])
  history=list_project_messages('eval',db=self.db)['messages']
  restored=next(m for m in history if m['id']==result['id'])
  self.assertEqual(restored['content'],result['content'])
  self.assertEqual(json.loads(restored['metadata_json'])['analysis_package'],result['analysis_package'])
  self.assertEqual(load_context(self.db,'eval')['recent_successes'][0]['message_id'],result['id'])
 def test_misplaced_repair_negative_variants_fail_without_replacing_last_success(self):
  seed=self.seed_captured_monthly_context()
  original,repaired=[d['output'] for d in MISPLACED['diagnostics']]
  predicate={'column':'ShipCountry','operator':'==','value':'Brazil'}
  for variant in ['years','filters','formula','unit','source','join','table_scope','chart_type','chart_scope','conflicting_compare','conflicting_filters','conflicting_chart_scope','unknown_relocation']:
   with self.subTest(variant=variant):
    bad,good=copy.deepcopy(original),copy.deepcopy(repaired)
    # Bind the intended stored output so these variants reach semantic repair
    # rather than stopping at the independent ambiguous-identity safeguard.
    for draft in (bad,good):draft['analysis_plan']['outputs'][0]['id']=seed['analysis_plan']['outputs'][0]['id']
    before=bad['analysis_plan']['outputs'][0]['parameters'];after=good['analysis_plan']['outputs'][0]['parameters']
    if variant=='years':after['years']=[2022]
    elif variant=='filters':before['metric']['filters']=[predicate]
    elif variant=='formula':after['metric']['expression']['args'][2]['args'][1]['column']='Quantity'
    elif variant=='unit':before['metric']['unit']='BRL';after['metric']['unit']='USD'
    elif variant=='source':
     good['analysis_plan']['source']['tables'][0]='olist.db::orders';after['source']=copy.deepcopy(good['analysis_plan']['source'])
    elif variant=='join':
     good['analysis_plan']['source']['join_keys'][0]['from_column']='Freight';after['source']=copy.deepcopy(good['analysis_plan']['source'])
    elif variant=='table_scope':after['output']['table']=False
    elif variant=='chart_type':after['output']['chart']='bar'
    elif variant=='chart_scope':good['analysis_plan']['chart_scope']={'required':True,'top_n':20}
    elif variant=='conflicting_compare':before['compare']=True
    elif variant=='conflicting_filters':before['metric']['filters']=[predicate];before['filters']=[{**predicate,'value':'USA'}];after['filters']=[predicate]
    elif variant=='conflicting_chart_scope':bad['analysis_plan']['chart_scope']={'required':True,'top_n':20}
    else:before['metric']['opaque']={'compare':before['metric'].pop('compare')}
    result,failed,provider,agent,saved=self.send(MISPLACED['question'],'northwind.db::Orders',bad,planner_replies=[good])
    self.assertTrue(failed,result);self.assertEqual(provider.call_count,2);agent.assert_not_called();self.assertIsNone(saved)
    self.assertNotIn('results',result)
    self.assertEqual(result['planner_diagnostics'][-1]['accepted'],False)
    self.assertEqual(load_context(self.db,'eval')['recent_successes'][0]['message_id'],seed['id'])
    self.assertEqual(len(list_saved_analyses('eval',self.db)),1)
 def test_schema_owned_duplicate_fields_and_canonical_meanings(self):
  original,repaired=copy.deepcopy([d['output'] for d in MISPLACED['diagnostics']])
  p=original['analysis_plan']['outputs'][0]['parameters'];target=repaired['analysis_plan']['outputs'][0]['parameters']
  a={'column':'ShipCountry','operator':'=','value':'Brazil'};b={'column':'Freight','operator':'>','value':0}
  p['metric']['filters']=[a,b];p['filters']=[b,a];target['filters']=[a,b]
  p['compare']=False;original['analysis_plan']['chart_scope']={'top_n':10}
  # Known predicate alias/order, formula association, and schema defaults are equivalent.
  args=target['metric']['expression']['args']
  target['metric']['expression']={'op':'multiply','args':[{'op':'multiply','args':args[:2]},args[2]]}
  guard_repair(original,repaired)
  self.assertIn('compare',original['analysis_plan']['outputs'][0]['parameters']['metric'])
 def test_unknown_and_ambiguous_relocations_are_rejected(self):
  original,repaired=[d['output'] for d in MISPLACED['diagnostics']]
  for variant in ['unknown_scope_container','unknown_filter_container','multiple_outputs','conflicting_nested_source']:
   with self.subTest(variant=variant):
    bad,good=copy.deepcopy(original),copy.deepcopy(repaired);p=bad['analysis_plan']['outputs'][0]['parameters']
    if variant=='unknown_scope_container':
     p['opaque']={'chart_scope':{'required':False,'top_n':10}}
    elif variant=='unknown_filter_container':
     predicate={'column':'ShipCountry','operator':'==','value':'Brazil'}
     p['opaque_conditions']=[predicate];good['analysis_plan']['outputs'][0]['parameters']['filters']=[predicate]
    elif variant=='multiple_outputs':
     extra=copy.deepcopy(bad['analysis_plan']['outputs'][0]);extra['id']='second';bad['analysis_plan']['outputs'].append(extra)
     extra=copy.deepcopy(good['analysis_plan']['outputs'][0]);extra['id']='second';good['analysis_plan']['outputs'].append(extra)
    else:p['source']['tables'][0]='olist.db::orders'
    with self.assertRaises(ValueError):guard_repair(bad,good,MISPLACED['diagnostics'][0]['error'].split(': ',1)[0])
 def test_repaired_plan_must_still_pass_strict_schema(self):
  original,repaired=[d['output'] for d in MISPLACED['diagnostics']]
  invalid=copy.deepcopy(repaired);invalid['analysis_plan']['outputs'][0]['parameters']['metric']['compare']=False
  with self.assertRaisesRegex(ValueError,'compare'):guard_repair(original,invalid)
 def test_wrong_source_and_units_cannot_bind_equivalent_population(self):
  from app.analysis.output_bindings import bind
  p={'group_by':['flag'],'aggregations':{'id':'count'}}
  result=execute('aggregation',p,pd.DataFrame({'flag':[0,1,1],'id':['a','b','c']}))
  parent={'id':'groups','tool':'aggregation','parameters':p,'source':{'tables':['one']},'result':result,'signature':'sig','step_index':0}
  spec={'id':'one','kind':'aggregation','group_by':[],'source_tables':['other'],'filters':[{'column':'flag','operator':'==','value':1}],'measures':[{'source_column':'id','operation':'count'}]}
  self.assertIsNone(bind(spec,parent))
  spec['source_tables']=['one'];spec['measures'][0].update(unit='BRL',divide_by=100,output='Amount')
  self.assertIsNone(bind(spec,parent))
  invalid=copy.deepcopy(spec);invalid['measures']=[{'source_column':'id','operation':'count'}];invalid['filters'][0]['value']=True
  self.assertIsNone(bind(invalid,parent))
 def test_explicit_cross_database_request_is_clearly_unsupported(self):
  plan={'intent':'SIMPLE','context_action':'standalone','analysis_plan':{'source':{'tables':['northwind.db::Products','olist.db::products']},'outputs':[{'id':'matched','kind':'aggregation','parameters':{'aggregations':{'ProductID':'count'}}}]}}
  r,failed,_,agent,_=self.send('Join northwind.db::Products to olist.db::products; that relationship must be declared.','northwind.db::Products',plan)
  self.assertTrue(failed);self.assertIn('Cross-database joins are not supported',r['content']);self.assertNotIn('results',r);agent.assert_not_called()
 def test_standalone_that_does_not_trigger_reference_heuristic(self):
  plan={'intent':'SIMPLE','context_action':'standalone','analysis_plan':{'source':{'tables':['olist.db::orders']},'outputs':[{'id':'orders','kind':'aggregation','parameters':{'aggregations':{'order_id':'count'}}}]}}
  self.send('Count all orders.','olist.db::orders',plan)
  r,failed,*_=self.send('Using olist.db::orders, count rows in that table.','olist.db::orders',plan)
  self.assertFalse(failed,r);self.assertFalse(r.get('clarification_required',False))

if __name__=='__main__':unittest.main()
