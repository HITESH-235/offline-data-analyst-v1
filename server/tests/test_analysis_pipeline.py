"""Recorded model responses, real chat dispatch/calculations/storage; no model requests."""
import copy,json,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.api.v1.chat import process_chat_message
from app.api.v1.projects import list_saved_analyses,list_project_messages
from app.models.chat import ChatRequest,DBChatHistory
from app.models.project import DBProject
from app.storage.sqlite.session import Base
from app.services.dataset_manager import DatasetManager
from app.services.analysis_package import OutputAccumulator,finalize,validate_requirements
from app.analysis_engine import AnalysisEngine
from app.sandbox.structured_outputs import verify_exports

CAPTURES=json.loads((Path(__file__).parent/'fixtures/analysis_pipeline_replays.json').read_text())
class PipelineReplayTest(unittest.TestCase):
 def setUp(self):
  self.engine=create_engine('sqlite://');Base.metadata.create_all(self.engine);self.db=Session(self.engine)
  self.db.add_all([DBProject(id='p',name='P'),DBProject(id='other',name='Other')]);self.db.commit()
 def tearDown(self):self.db.close();self.engine.dispose()
 def send(self,question,steps,specs,chart=None,selection=None,intent='SIMPLE'):
  selection=selection or {'tables_needed':steps[0]['tables'],'join_keys':steps[0].get('join_keys',[])}
  plan={'intent':intent,'context_action':'standalone','completion_contract':{'outputs':specs,**({'chart_scope':chart} if chart else {})}}
  replies=[json.dumps({'action':'tool_call','tool':s['tool'],'parameters':s['parameters']}) for s in steps]+[json.dumps({'action':'final_answer','content':'I verified 999999 orders; correlation proves independence.'})]
  with patch('app.llm.client.OllamaClient.call_model',side_effect=[json.dumps(plan),json.dumps(selection)]) as routing,patch('app.llm.agent.OllamaClient.call_model_chat',side_effect=replies):
   result,failed=process_chat_message(ChatRequest(project_id='p',dataset_id=selection['tables_needed'][0],message=question),self.db,lambda s:None)
  self.assertEqual(routing.call_count,2)
  self.assertNotIn('999999',result['content']);self.assertNotIn('proves independence',result['content'])
  metadata=json.loads(self.db.get(DBChatHistory,result['id']).metadata_json)
  self.assertEqual(metadata['analysis_package'],result['analysis_package'])
  self.db.close();self.db=Session(self.engine)
  history=list_project_messages('p',None,self.db)['messages']
  self.assertEqual(json.loads(next(m for m in history if m['id']==result['id'])['metadata_json'])['analysis_package'],result['analysis_package'])
  if result['analysis_package']['tables']:
   saved=next(s for s in list_saved_analyses('p',self.db) if s['id']==result['id'])
   self.assertEqual(saved['analysisPackage'],result['analysis_package']);self.assertEqual(saved['result'],result['results'])
  return result,failed
 def test_captured_status_and_currency_chart_do_not_replace_calculation(self):
  for capture in CAPTURES[:2]:
   group=capture['steps'][0]['parameters']['group_by'];column=next(iter(capture['steps'][0]['parameters']['aggregations']))
   measure={'source_column':column,'operation':'count' if column=='order_id' else 'sum'}
   if column!='order_id':measure.update(unit='BRL',divide_by=100,output='Total Payment Value (BRL)')
   spec={'id':'main','kind':'aggregation','group_by':group,'scope':{'mode':'all'},'measures':[measure]}
   r,failed=self.send(capture['question'],capture['steps'],[spec],{'required':True,'top_n':10})
   self.assertFalse(failed,r['content']);table=r['results'];self.assertLess(table['row_count'],10)
   self.assertEqual(r['analysis_package']['charts'][0]['table_id'],'main')
   if column=='order_id':self.assertEqual(sum(row['Order Count'] for row in table['data']),99441)
   else:self.assertEqual(next(row['Total Payment Value (BRL)'] for row in table['data'] if row['payment_type']=='credit_card'),12542084.19)
 def test_all_states_table_is_not_chart_top_ten(self):
  c=CAPTURES[2];r,failed=self.send(c['question'],c['steps'],[{'id':'states','kind':'aggregation','group_by':['customer_state'],'measures':[{'source_column':'order_id','operation':'count'}],'scope':{'mode':'all'}}],{'required':True,'top_n':10})
  self.assertFalse(failed,r['content']);self.assertEqual(r['results']['row_count'],27)
  self.assertEqual(sum(row['Order Count'] for row in r['results']['data']),99441)
  self.assertEqual(r['analysis_package']['chart_scope']['top_n'],10)
 def test_missing_requested_metric_is_incomplete_until_actually_calculated(self):
  c=CAPTURES[3];expression={'op':'subtract','args':[{'column':'Total Orders'},{'column':'Orders With Payments'}]}
  spec={'id':'coverage','kind':'aggregation','group_by':['order_status'],'columns':['Orders Without Payments'],'measures':[{'output':'Orders Without Payments','derived':expression}]}
  r,failed=self.send(c['question'],c['steps'],[spec]);self.assertTrue(failed);self.assertEqual(r['analysis_status'],'incomplete')
  steps=copy.deepcopy(c['steps']);steps[0]['parameters']['derived_measures']=[{'name':'Orders Without Payments','expression':expression}]
  r,failed=self.send(c['question'],steps,[spec]);self.assertFalse(failed,r['content'])
  self.assertEqual(sum(row['Orders Without Payments'] for row in r['results']['data']),1)
 def test_northwind_product_join_matches_all_sqlite_rows(self):
  tables=['northwind.db::Products','northwind.db::Order Details'];keys=[{'from_table':tables[1],'from_column':'ProductID','to_table':tables[0],'to_column':'ProductID'}]
  p={'group_by':['ProductName'],'aggregations':{'Quantity':'sum'},'sort_by':'Quantity','ascending':False}
  steps=[{'tool':'aggregation','parameters':p,'tables':tables,'join_keys':keys},{'tool':'visualization','parameters':{'chart_type':'bar','x':'ProductName','y':'Quantity'},'tables':tables}]
  r,failed=self.send('Rank products by summed units sold across all orders.',steps,[{'id':'products','kind':'aggregation','group_by':['ProductName'],'source_tables':tables,'scope':{'mode':'all'},'measures':[{'source_column':'Quantity','operation':'sum'}]}],{'required':True})
  self.assertFalse(failed,r['content'])
  with sqlite3.connect(DatasetManager.get_dataset(None,tables[0]).filepath) as db:expected=db.execute('SELECT p.ProductName,SUM(d.Quantity) FROM Products p JOIN "Order Details" d ON p.ProductID=d.ProductID GROUP BY p.ProductName ORDER BY 2 DESC,1').fetchall()
  self.assertEqual([(row['ProductName'],row['Quantity']) for row in r['results']['data']],expected)
 def test_independent_sources_can_return_multiple_tables_and_charts(self):
  specs=[];steps=[]
  for ident,table,group,column,op in [('status','orders','order_status','order_id','count'),('payments','order_payments','payment_type','payment_value_cents','sum')]:
   name='olist.db::'+table;specs.append({'id':ident,'kind':'aggregation','source_tables':[name],'group_by':[group],'measures':[{'source_column':column,'operation':op}]})
   p={'output_id':ident,'group_by':[group],'aggregations':{column:op}}
   steps.append({'tool':'aggregation','parameters':p,'tables':[name]})
  r,failed=self.send('Report status counts and payment totals as separate calculations.',steps,specs,selection={'tables_needed':[s['source_tables'][0] for s in specs]})
  self.assertFalse(failed,r['content']);pack=r['analysis_package'];self.assertEqual(len(pack['tables']),2);self.assertEqual(len(pack['charts']),2)
  for table,spec in zip(pack['tables'],specs):self.assertEqual(table['source']['tables'],spec['source_tables'])
 def test_unseen_vocabulary_negative_nulls_and_scope(self):
  with tempfile.TemporaryDirectory() as root:
   pd.DataFrame({'depot':['east','west','north','east'],'amount_cents':[125,-50,None,25],'parcel_id':['a','b','c','d']}).to_csv(Path(root)/'parcels.csv',index=False)
   c={'id':'depots','kind':'aggregation','group_by':['depot'],'scope':{'mode':'all'},'measures':[{'source_column':'amount_cents','operation':'sum','output':'Net (BRL)','unit':'BRL','divide_by':100}]}
   steps=[{'tool':'aggregation','parameters':{'group_by':['depot'],'aggregations':{'amount_cents':'sum'},'limit':1,'sort_by':'amount_cents','ascending':False},'tables':['parcels.csv']}]
   with patch('app.services.dataset_manager.settings.DATASETS_DIR',root),patch('app.api.v1.chat.MetadataService.get_profile',return_value={'columns':['depot','amount_cents','parcel_id']}),patch('app.services.metadata_service.MetadataService.get_catalog_index',return_value={'tables':{'parcels.csv':{'columns':['depot','amount_cents','parcel_id']}},'relationships':[]}):
    r,failed=self.send('Return all depots with a Top 5 chart; compute net receipts in BRL.',steps,[c],{'required':True,'top_n':5})
   self.assertFalse(failed,r['content']);self.assertEqual({row['depot']:row['Net (BRL)'] for row in r['results']['data']},{'east':1.5,'west':-.5,'north':None})

 def test_actual_python_subprocess_delivers_verified_named_outputs(self):
  from app.core.config import settings
  with tempfile.TemporaryDirectory() as root:
   Path(root,'readings.csv').write_text('location,reading\nnorth,2\nsouth,-1\nnorth,3\n')
   p={'group_by':['location'],'aggregations':{'reading':'sum'}}
   code='summary=df.groupby("location",dropna=False)["reading"].sum().reset_index()\nanalysis_tables={"readings":summary}\nanalysis_plans={"readings":{"tool":"aggregation","parameters":'+repr(p)+'}}\nfig=px.bar(summary,x="location",y="reading")\nfig.write_html("output_chart.html")'
   steps=[{'tool':'run_code','parameters':{'code':code},'tables':['readings.csv']}]
   with patch.object(settings,'DATASETS_DIR',root),patch.object(settings,'WORKSPACE_DIR',root+'/workspace'),patch('app.api.v1.chat.MetadataService.get_profile',return_value={'columns':['location','reading']}),patch('app.services.metadata_service.MetadataService.get_catalog_index',return_value={'tables':{'readings.csv':{'columns':['location','reading']}},'relationships':[]}):
    r,failed=self.send('Calculate total readings for each location and plot them.',steps,[{'id':'readings','kind':'aggregation','group_by':['location'],'measures':[{'source_column':'reading','operation':'sum'}]}],{'required':True},intent='COMPLEX')
   self.assertFalse(failed,r['content']);self.assertEqual(r['results']['data'],[{'location':'north','reading':5},{'location':'south','reading':-1}]);self.assertEqual(len(r['artifacts']),1)
   self.assertEqual(r['analysis_package']['charts'][-1]['validation'],'export_only')

 def test_olist_followup_sequence_reload_failure_and_independent_sql(self):
  from app.services.analysis_context import load_context
  tables=['olist.db::order_financials','olist.db::orders']
  keys=[{'from_table':tables[0],'from_column':'order_id','to_table':tables[1],'to_column':'order_id'}]
  state={'source':{'tables':tables,'join_keys':keys},'metric':{'name':'Paid Total (BRL)','unit':'BRL','aggregation':'sum','expression':{'op':'multiply','args':[{'column':'payment_total_cents'},{'value':0.01}]}},'date_column':'order_purchase_timestamp','years':[2017],'grain':'month','compare':False,'filters':[{'column':'has_payments','operator':'==','value':1}],'output':{'table':True,'chart':'line'}}
  def send(question,state,inherit=False):
   plan={'intent':'SIMPLE','context_action':'inherit' if inherit else 'standalone','resolved_analysis':state}
   with patch('app.llm.client.OllamaClient.call_model',return_value=json.dumps(plan)),patch('app.llm.agent.OllamaClient.call_model_chat') as model:
    r,failed=process_chat_message(ChatRequest(project_id='p',dataset_id=tables[0],message=question),self.db,lambda stage:None)
   self.assertFalse(failed,r['content']);model.assert_not_called();return r
  first=send('Report monthly paid receipts for 2017 in BRL.',state)
  quarter=copy.deepcopy(state);quarter['grain']='quarter'
  send('Regroup the same receipts quarterly.',quarter,True)
  comparison=copy.deepcopy(quarter);comparison.update(years=[2017,2018],compare=True)
  last=send('Compare these periods with the following year.',comparison,True)
  # A failed turn must not replace the successful comparison.
  bad=copy.deepcopy(comparison);bad['date_column']='missing_timestamp'
  with patch('app.llm.client.OllamaClient.call_model',return_value=json.dumps({'intent':'SIMPLE','context_action':'inherit','resolved_analysis':bad})):
   failure,failed=process_chat_message(ChatRequest(project_id='p',dataset_id=tables[0],message='Use a nonexistent timestamp.'),self.db,lambda stage:None)
  self.assertTrue(failed)
  self.db.close();self.db=Session(self.engine)
  self.assertEqual(load_context(self.db,'p')['recent_successes'][0]['message_id'],last['id'])
  monthly=send('Show that monthly instead.',{'grain':'month'},True)
  result=monthly['results'];self.assertEqual(result['row_count'],12);self.assertEqual(len(result['calendar_chart']['series']),2)
  with sqlite3.connect(DatasetManager.get_dataset(None,tables[0]).filepath) as db:
   expected=db.execute("SELECT CAST(strftime('%Y',o.order_purchase_timestamp) AS INT),CAST(strftime('%m',o.order_purchase_timestamp) AS INT),SUM(f.payment_total_cents)/100.0 FROM order_financials f JOIN orders o ON f.order_id=o.order_id WHERE f.has_payments=1 AND strftime('%Y',o.order_purchase_timestamp) IN ('2017','2018') GROUP BY 1,2 ORDER BY 1,2").fetchall()
  for year,month,total in expected:self.assertAlmostEqual(result['data'][month-1][f'Paid Total (BRL) {year}'],total,places=5)
  self.assertAlmostEqual(result['verification']['annual_totals']['2017'],7249746.73,places=5)
  self.assertAlmostEqual(result['verification']['annual_totals']['2018'],8699763.05,places=5)
  self.assertEqual(monthly['analysis_package']['status'],'complete')
  # Explicit new scope retains no old years/filter/source.
  standalone=copy.deepcopy(state);standalone.update(source={'tables':['olist.db::orders'],'join_keys':[]},metric={'name':'Orders','aggregation':'count'},filters=[],years=[2018],grain='year')
  final=send('Count orders in 2018 only.',standalone)
  self.assertEqual(final['analysis_context']['years'],[2018]);self.assertEqual(final['analysis_context']['filters'],[])

 def test_statistics_can_complete_without_unsolicited_table_or_chart(self):
  from app.core.config import settings
  with tempfile.TemporaryDirectory() as root:
   Path(root,'measurements.csv').write_text('value\n4\n')
   steps=[{'tool':'statistics','parameters':{'columns':['value']},'tables':['measurements.csv']}]
   with patch.object(settings,'DATASETS_DIR',root),patch('app.api.v1.chat.MetadataService.get_profile',return_value={'columns':['value']}),patch('app.services.metadata_service.MetadataService.get_catalog_index',return_value={'tables':{'measurements.csv':{'columns':['value']}},'relationships':[]}):
    r,failed=self.send('Summarize the measurement without a chart.',steps,[{'id':'summary','kind':'statistics','columns':['value'],'measures':[{'source_column':'value','operation':'mean'}]}])
   self.assertFalse(failed,r['content']);self.assertNotIn('results',r);self.assertEqual(r['analysis_package']['charts'],[]);self.assertEqual(r['analysis_package']['facts'][0]['statistics']['value']['mean'],4)

 def test_stream_delivers_progress_and_truthful_terminal_package(self):
  import asyncio
  from sqlalchemy.pool import StaticPool
  from sqlalchemy.orm import sessionmaker
  from app.api.v1.chat import stream_chat_message
  engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
  Base.metadata.create_all(engine);factory=sessionmaker(bind=engine)
  with factory() as db:db.add(DBProject(id='stream',name='Stream'));db.commit()
  request=ChatRequest(project_id='stream',dataset_id='olist.db::orders',message='Count orders for each status.')
  plan={'intent':'SIMPLE','completion_contract':{'outputs':[{'id':'counts','kind':'aggregation','group_by':['order_status'],'measures':[{'source_column':'order_id','operation':'count'}]}]}}
  action={'action':'tool_call','tool':'aggregation','parameters':{'group_by':['order_status'],'aggregations':{'order_id':'count'}}}
  async def consume():
   response=await stream_chat_message(request)
   return [json.loads(line) async for line in response.body_iterator]
  try:
   for calculated,terminal in [(True,'completed'),(False,'incomplete')]:
    responses=([json.dumps(action)] if calculated else [])+[json.dumps({'action':'final_answer','content':'Done'})]
    with patch('app.api.v1.chat.SessionLocal',factory),patch('app.llm.client.OllamaClient.call_model',side_effect=[json.dumps(plan),json.dumps({'tables_needed':['olist.db::orders']})]),patch('app.llm.agent.OllamaClient.call_model_chat',side_effect=responses):
     events=asyncio.run(consume())
    self.assertEqual(events[-1]['stage'],terminal);self.assertIn('selecting_tables',[e['stage'] for e in events[:-1]])
    pack=events[-1]['result']['analysis_package'];self.assertEqual(pack['status'],'complete' if calculated else 'incomplete')
    if calculated:self.assertEqual(sum(row['Order Count'] for row in pack['tables'][0]['result']['data']),99441)
  finally:engine.dispose()

class PackageBoundaryTest(unittest.TestCase):
 def test_failed_replacement_retains_valid_table_and_facts(self):
  df=pd.DataFrame({'site':['x','y'],'units':[2,3]});p={'group_by':['site'],'aggregations':{'units':'sum'}}
  r=AnalysisEngine.execute_plan(None,'t',{'aggregation':p},dataframe=df)
  contract={'outputs':[{'id':'totals','kind':'aggregation','columns':['site','units'],'group_by':['site'],'measures':[{'source_column':'units','operation':'sum'}]}]}
  a=OutputAccumulator();a.record('aggregation',p,r,{'tables':['fixture']},0,'totals',contract)
  with self.assertRaises(ValueError):a.record('aggregation',{'aggregations':{'units':'sum'}},{'columns':['wrong'],'data':[{'wrong':0}]},{'tables':['fixture']},1,'totals',contract)
  final=finalize({'failed':True,'content':'unverified prose','analysis_outputs':a.export()},'question','p','response',contract)
  self.assertEqual(final['results'],r);self.assertEqual(final['analysis_status'],'incomplete');self.assertIn('2 of 2 result rows',final['content'])
 def test_python_export_requires_recomputed_values(self):
  df=pd.DataFrame({'group':['a','a','b'],'value':[10,-2,3]});p={'group_by':['group'],'aggregations':{'value':'sum'}}
  expected=AnalysisEngine.execute_plan(None,'t',{'aggregation':p},dataframe=df)
  export={'id':'summary','result':expected,'plan':{'tool':'aggregation','parameters':p}}
  verified=verify_exports([export],df);a=OutputAccumulator();a.record('run_code',{}, {'verified_tables':verified},{'tables':['fixture']},0)
  final=finalize({'analysis_outputs':a.export()},'calculate','p','id',{'outputs':[{'id':'summary','kind':'aggregation','group_by':['group'],'measures':[{'source_column':'value','operation':'sum'}]}]})
  self.assertEqual(final['analysis_status'],'complete')
  export['result']['data'][0]['value']=999
  with self.assertRaisesRegex(ValueError,'numeric'):verify_exports([export],df)
 def test_chart_capture_or_prose_does_not_establish_completion(self):
  for raw in [{'content':'Verified 100 observations'},{'content':'Python ran','artifacts':[{'id':'png','kind':'png'}]}]:
   r=finalize(raw,'calculate','p','id',{'outputs':[{'id':'required','kind':'aggregation','group_by':[],'measures':[{'source_column':'value','operation':'sum'}]}]})
   self.assertEqual(r['analysis_status'],'incomplete');self.assertNotIn('results',r);self.assertNotIn('Verified 100',r['content'])
 def test_contract_rejects_unsupported_fields(self):
  with self.assertRaises(ValueError):validate_requirements({'outputs':[{'id':'a','kind':'aggregation','invented':True}]})

if __name__=='__main__':unittest.main()
