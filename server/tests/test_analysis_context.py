import copy,json,sqlite3,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.api.v1.chat import process_chat_message
from app.analysis.calendar import calculate
from app.services.analysis_context import load_context,from_result
from app.services.dataset_manager import DatasetManager
from app.llm.table_selector import TableSelector
from app.models.chat import ChatRequest,DBChatHistory
from app.models.project import DBProject
from app.storage.sqlite.session import Base

TABLES=['northwind.db::Orders','northwind.db::Order Details']
KEYS=[{'from_table':TABLES[1],'from_column':'OrderID','to_table':TABLES[0],'to_column':'OrderID'}]
STATE={'source':{'tables':TABLES,'join_keys':KEYS},'metric':{'name':'Revenue','aggregation':'sum','expression':{'op':'multiply','args':[{'op':'multiply','args':[{'column':'UnitPrice'},{'column':'Quantity'}]},{'op':'subtract','args':[{'value':1},{'column':'Discount'}]}]}},'date_column':'OrderDate','years':[2021],'grain':'month','compare':False,'filters':[],'output':{'table':True,'chart':'line'}}

class FollowupTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.frame=DatasetManager.load_joined_dataframe(TABLES,KEYS)
  path=Path(DatasetManager.get_dataset(None,TABLES[0]).filepath)
  with sqlite3.connect(path) as db:
   cls.sql=db.execute('''SELECT CAST(strftime('%Y',o.OrderDate) AS INT), (CAST(strftime('%m',o.OrderDate) AS INT)+2)/3, SUM(d.UnitPrice*d.Quantity*(1-d.Discount)) FROM Orders o JOIN "Order Details" d ON o.OrderID=d.OrderID WHERE strftime('%Y',o.OrderDate) IN ('2021','2022') GROUP BY 1,2 ORDER BY 1,2''').fetchall()
   cls.annual=dict(db.execute('''SELECT CAST(strftime('%Y',o.OrderDate) AS INT),SUM(d.UnitPrice*d.Quantity*(1-d.Discount)) FROM Orders o JOIN "Order Details" d ON o.OrderID=d.OrderID WHERE strftime('%Y',o.OrderDate) IN ('2021','2022') GROUP BY 1''').fetchall())
 def setUp(self):
  self.engine=create_engine('sqlite://');Base.metadata.create_all(self.engine);self.db=Session(self.engine)
  self.db.add_all([DBProject(id='p',name='P'),DBProject(id='other',name='Other')]);self.db.commit()
 def tearDown(self):self.db.close();self.engine.dispose()
 def send(self,message,state,action='standalone'):
  before=load_context(self.db,'p')
  plan={'intent':'SIMPLE','context_action':action,'analysis_plan':{'source':state['source'],'outputs':[{'id':'calendar','kind':'calendar_aggregate','parameters':state}]}}
  if action=='inherit' and before['recent_successes']:
   prior=before['recent_successes'][0];plan['reference_message_id']=prior['message_id']
   old=prior['analysis']['plan']['outputs'][0]['parameters']
   plan['changed_fields']=[key for key in ('years','compare','grain','filters','metric','date_column') if state.get(key)!=old.get(key)]
  request=ChatRequest(project_id='p',dataset_id=TABLES[0],message=message)
  with patch('app.api.v1.chat.QueryPlanner.plan_query',return_value=plan) as planner,patch('app.llm.agent.OllamaClient.call_model_chat') as model:
   result,failed=process_chat_message(request,self.db,lambda stage:None)
  self.assertFalse(failed,result);model.assert_not_called()
  return result,planner.call_args.kwargs['analysis_context'] if planner.call_args else before
 def test_three_turns_reload_failure_and_sql_comparison(self):
  first,_=self.send('Show monthly revenue for 2021 after discounts.',copy.deepcopy(STATE))
  quarter=copy.deepcopy(STATE);quarter['grain']='quarter'
  second,history=self.send('Now show that quarterly.',quarter,'inherit')
  self.assertEqual(history['recent_successes'][0]['analysis']['plan']['outputs'][0]['parameters']['years'],[2021])
  self.assertNotIn('data',history['recent_successes'][0]['analysis'])
  self.assertEqual(second['results']['row_count'],4)
  for row,(_,q,value) in zip(second['results']['data'],self.sql[:4]):
   self.assertEqual(row['Quarter'],f'2021-Q{q}');self.assertAlmostEqual(row['Revenue'],value,places=5)
  self.assertAlmostEqual(sum(row['Revenue'] for row in second['results']['data']),self.annual[2021],places=5)
  self.db.add(DBChatHistory(id='failed',project_id='p',role='assistant',content='Failed',metadata_json=json.dumps({'analysis_failed':True,'calculation':{'steps':[{'status':'failed'}]}})));self.db.commit()
  self.db.close();self.db=Session(self.engine)
  comparison=copy.deepcopy(quarter);comparison.update(years=[2021,2022],compare=True)
  third,history=self.send('Compare those quarters with 2022.',comparison,'inherit')
  self.assertEqual(history['recent_successes'][0]['analysis']['plan']['outputs'][0]['parameters']['grain'],'quarter')
  self.assertEqual(third['results']['row_count'],4)
  for year in (2021,2022):
   for row,(_,q,value) in zip(third['results']['data'],[r for r in self.sql if r[0]==year]):
    self.assertEqual(row['Quarter'],f'Q{q}');self.assertAlmostEqual(row[f'Revenue {year}'],value,places=5)
   self.assertAlmostEqual(sum(r[f'Revenue {year}'] for r in third['results']['data']),self.annual[year],places=5)
  self.assertEqual(third['analysis_context']['source']['tables'],TABLES)
  self.assertEqual(load_context(self.db,'other')['recent_successes'],[])
 def test_monthly_comparison_with_and_without_reload(self):
  path=Path(DatasetManager.get_dataset(None,TABLES[0]).filepath)
  with sqlite3.connect(path) as db:
   expected=db.execute('''SELECT CAST(strftime('%Y',o.OrderDate) AS INT),CAST(strftime('%m',o.OrderDate) AS INT),SUM(d.UnitPrice*d.Quantity*(1-d.Discount)) FROM Orders o JOIN "Order Details" d ON o.OrderID=d.OrderID WHERE strftime('%Y',o.OrderDate) IN ('2021','2022') GROUP BY 1,2 ORDER BY 1,2''').fetchall()
  for reload in [False,True]:
   with self.subTest(reload=reload):
    first,_=self.send('Monthly revenue for 2021 after discounts.',copy.deepcopy(STATE))
    quarter=copy.deepcopy(STATE);quarter['grain']='quarter'
    self.send('Now show that quarterly.',quarter,'inherit')
    comparison=copy.deepcopy(quarter);comparison.update(years=[2021,2022],compare=True)
    third,_=self.send('Compare those quarters with 2022.',comparison,'inherit')
    if reload:
     self.db.close();self.db=Session(self.engine)
    restored=load_context(self.db,'p')['recent_successes'][0]
    self.assertEqual(restored['message_id'],third['id'])
    self.assertEqual(restored['analysis']['plan']['outputs'][0]['parameters']['years'],[2021,2022])
    monthly=copy.deepcopy(comparison);monthly['grain']='month'
    response,_=self.send('Show that monthly instead.',monthly,'inherit')
    result=response['results'];state=response['analysis_context']
    self.assertEqual(result['row_count'],12)
    self.assertEqual(result['columns'],['Month','Revenue 2021','Revenue 2022'])
    self.assertEqual(result['calendar_chart']['series'],['Revenue 2021','Revenue 2022'])
    for key in ('years','compare','metric','source','filters','date_column','output'):
     self.assertEqual(state[key],third['analysis_context'][key])
    self.assertEqual(state['grain'],'month')
    for year,month,total in expected:
     self.assertAlmostEqual(result['data'][month-1][f'Revenue {year}'],total,places=5)
    for year in (2021,2022):
     self.assertAlmostEqual(sum(row[f'Revenue {year}'] for row in result['data']),self.annual[year],places=5)
     self.assertIn(f'{self.annual[year]:,.2f}',response['content'])
    saved=json.loads(self.db.get(DBChatHistory,response['id']).metadata_json)
    self.assertEqual(saved['analysis_context'],{'version':1,'plan':response['analysis_plan']})
    self.assertEqual(saved['results']['analysis_context'],state)
    self.assertEqual(saved['context_resolution']['reference_message_id'],third['id'])
    self.assertEqual(saved['context_resolution']['updated_fields'],['outputs.calendar.parameters.grain'])
    self.assertEqual(load_context(self.db,'p')['recent_successes'][0]['analysis'],saved['analysis_context'])
 def test_result_context_is_authoritative_and_grouping_edits_are_narrow(self):
  comparison=copy.deepcopy(STATE);comparison.update(years=[2021,2022],compare=True,grain='quarter')
  meta={'question':'Comparison','analysis_context':STATE,'results':{'analysis_context':comparison},'calculation':{'steps':[{'status':'succeeded','tool':'calendar_aggregate','tables':TABLES,'join_keys':KEYS}]}}
  self.db.add(DBChatHistory(id='authoritative',project_id='p',role='assistant',content='Done',metadata_json=json.dumps(meta)));self.db.commit()
  history=load_context(self.db,'p')
  self.assertEqual(history['recent_successes'][0]['analysis']['plan']['outputs'][0]['parameters'],{k:v for k,v in comparison.items() if k!='source'})
  self.assertIsNone(from_result(meta))  # New writers require an executed canonical plan.
 def test_many_failed_turns_cannot_push_success_out_of_bounded_history(self):
  self.send('Revenue by month.',copy.deepcopy(STATE))
  for i in range(25):
   self.db.add(DBChatHistory(id=f'failure-{i}',project_id='p',role='assistant',content='Failed',metadata_json=json.dumps({'analysis_failed':True})))
  self.db.commit()
  self.assertEqual(load_context(self.db,'p')['recent_successes'][0]['analysis']['plan']['outputs'][0]['parameters']['years'],[2021])
 def test_standalone_source_and_metric_changes_do_not_inherit_years(self):
  self.send('Revenue by month.',copy.deepcopy(STATE))
  state=copy.deepcopy(STATE);state.update(years=[2022],grain='quarter')
  state['source']={'tables':[TABLES[0]],'join_keys':[]};state['metric']={'name':'Freight','aggregation':'sum','expression':{'column':'Freight'}}
  response,_=self.send('Show quarterly Freight in Orders for 2022.',state)
  self.assertEqual(response['analysis_context']['years'],[2022]);self.assertEqual(response['analysis_context']['metric']['name'],'Freight')
  self.assertEqual(response['calculation']['steps'][0]['tables'],[TABLES[0]])
 def test_ambiguity_preserves_last_success(self):
  self.send('Revenue by month.',copy.deepcopy(STATE))
  with patch('app.api.v1.chat.QueryPlanner.plan_query',return_value={'intent':'SIMPLE','context_action':'clarify','clarification':'Which metric should I compare?'}),patch('app.api.v1.chat.Agent.run') as agent:
   result,failed=process_chat_message(ChatRequest(project_id='p',dataset_id=TABLES[0],message='Compare that with the other one.'),self.db,lambda stage:None)
  agent.assert_not_called();self.assertTrue(result['clarification_required'])
  self.assertEqual(load_context(self.db,'p')['recent_successes'][0]['analysis']['plan']['outputs'][0]['parameters']['years'],[2021])
 def test_legacy_python_context_is_bounded_and_skips_advice(self):
  code="df['net'] = df['UnitPrice'] * df['Quantity'] * (1-df['Discount'])\nmask=df['Date'].dt.year==2021"
  meta={'question':'Net sales in 2021','calculation':{'steps':[{'tool':'run_code','status':'succeeded','tables':TABLES,'join_keys':KEYS,'parameters':{'code':code}}]},'results':{'data':[{'huge_raw_dataset':'never send this'}]}}
  self.db.add(DBChatHistory(id='legacy',project_id='p',role='assistant',content='Done',metadata_json=json.dumps(meta)));self.db.commit()
  context=load_context(self.db,'p');serialized=json.dumps(context)
  self.assertNotIn('huge_raw_dataset',serialized);self.assertNotIn('parameters": {"code"',serialized)
  self.assertEqual(context['recent_successes'][0]['code_facts']['years'],[2021])
  self.assertIsNone(from_result(meta))
 def test_table_identifiers_validated_and_cross_database_guard_retained(self):
  catalog={t:{} for t in TABLES}
  with self.assertRaisesRegex(ValueError,'northwind.db'):
   TableSelector.validate_selection({'tables_needed':[TABLES[0],'northwind.db']},catalog)
  from types import SimpleNamespace
  datasets=[SimpleNamespace(id='a.db::T',filepath='/tmp/a.db',table_name='T'),SimpleNamespace(id='b.db::U',filepath='/tmp/b.db',table_name='U')]
  with patch.object(DatasetManager,'get_dataset',side_effect=datasets),self.assertRaisesRegex(ValueError,'same SQLite database'):
   DatasetManager.load_joined_dataframe(['a.db::T','b.db::U'])
 def test_generic_expression_and_filters_are_retained(self):
  state=copy.deepcopy(STATE);state['filters']=[{'column':'Quantity','operator':'>','value':10}];state['grain']='quarter'
  result=calculate(self.frame,state)
  self.assertEqual(result['analysis_context']['filters'],state['filters'])
  state['metric']['expression']={'op':'multiply','args':[{'column':'UnitPrice'},{'column':'Quantity'},{'op':'subtract','args':[{'value':1},{'column':'Discount'}]}]}
  np.testing.assert_allclose([r['Revenue'] for r in calculate(self.frame,state)['data']],[r['Revenue'] for r in result['data']])
  with self.assertRaises(ValueError):calculate(self.frame,{**state,'metric':{'name':'Bad','aggregation':'sum','expression':{'column':'missing'}}})

if __name__=='__main__':unittest.main()
