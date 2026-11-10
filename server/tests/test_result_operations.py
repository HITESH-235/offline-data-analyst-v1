import copy,json,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.analysis_engine import AnalysisEngine
from app.analysis.filtering import filter_data
from app.analysis.comparison_summary import calculate
from app.api.v1.chat import process_chat_message
from app.api.v1.projects import list_saved_analyses,list_project_messages
from app.models.chat import ChatRequest
from app.models.project import DBProject
from app.storage.sqlite.session import Base
from app.services.dataset_manager import DatasetManager

DATE_PARAMS={'column':'actual','value_column':'estimate','operator':'>','value_type':'date','date_part':'date','matched_label':'Late','filters':[{'column':'status','operator':'==','value':'delivered'}]}

class ResultOperationsTest(unittest.TestCase):
 def test_counts_are_named_measures_and_sort_aliases_resolve(self):
  frame=pd.DataFrame({'order_id':['a','b','c'],'status':['x','y','x']})
  for sort in ['order_id','Order Count','count']:
   r=AnalysisEngine.execute_plan(None,'test',{'aggregation':{'group_by':['status'],'aggregations':{'order_id':'count'},'sort_by':sort,'ascending':False}},dataframe=frame,validate_tool_arguments=True)
   self.assertEqual(r['columns'],['status','Order Count']);self.assertEqual(r['data'][0],{'status':'x','Order Count':2})
   self.assertEqual(r['measure_provenance']['Order Count']['source_column'],'order_id')
 def test_conversion_missing_groups_limit_and_sort_execute_on_rows(self):
  frame=pd.DataFrame({'category':['A',None,'B','A'],'price_cents':[101,250,100,102]})
  params={'group_by':['category'],'aggregations':{'price_cents':'sum'},'transforms':[{'column':'price_cents','divide_by':100,'as':'Price (BRL)','unit':'BRL'}],'fill_missing':{'category':'Unknown'},'limit':2,'sort_by':'price_cents','ascending':False}
  r=AnalysisEngine.execute_plan(None,'test',{'aggregation':params},dataframe=frame,validate_tool_arguments=True)
  self.assertEqual(r['data'],[{'category':'Unknown','Price (BRL)':2.5},{'category':'A','Price (BRL)':2.03}]);self.assertEqual(r['units'],{'Price (BRL)':'BRL'})
  self.assertEqual(r['result_scope']['full_group_count'],3)
  all_params={'group_by':['category'],'aggregations':{'price_cents':'sum'},'transforms':[{'column':'price_cents','divide_by':100,'as':'Price (BRL)','unit':'BRL'}],'fill_missing':{'category':'Unknown'}}
  self.assertNotIn('limit',all_params)
  self.assertNotIn('limit',all_params) # Chart scope never edits table scope.
  self.assertEqual(len(AnalysisEngine.execute_plan(None,'t',{'aggregation':all_params},dataframe=frame)['data']),3)
 def test_invalid_transforms_and_unsupported_fields_fail(self):
  frame=pd.DataFrame({'A':[1,2]})
  for patch_params in [{'transforms':[{'column':'A','divide_by':0,'as':'X'}]},{'transforms':[{'column':'missing','divide_by':100,'as':'X'}]},{'output_names':{'A':''}},{'limit':2},{'invented':True}]:
   with self.subTest(params=patch_params),self.assertRaises(ValueError):AnalysisEngine.execute_plan(None,'t',{'aggregation':{'aggregations':{'A':'sum'},**patch_params}},dataframe=frame,validate_tool_arguments=True)
 def test_requested_brl_conversion_overrides_model_only_scope_and_null_sum_stays_missing(self):
  p={'aggregations':{'money_cents':'sum'},'transforms':[{'column':'money_cents','divide_by':100,'as':'Money (BRL)','unit':'BRL'}]}
  self.assertEqual(p['transforms'][0]['divide_by'],100);self.assertEqual(p['transforms'][0]['unit'],'BRL')
  r=AnalysisEngine.execute_plan(None,'t',{'aggregation':p},dataframe=pd.DataFrame({'money_cents':[None,None]}))
  self.assertIsNone(r['data'][0]['Money (BRL)'])
 def test_calendar_comparison_nulls_and_same_day_times(self):
  df=pd.DataFrame({'status':['delivered']*5+['canceled'],'actual':['2020-01-01 23:59:59','2020-01-02',None,'2020-01-01','2020-01-01','2020-02-01'],'estimate':['2020-01-01 00:00:00','2020-01-01','2020-01-01',None,'2020-01-02','2020-01-01']})
  r=calculate(df,DATE_PARAMS);f=r['comparison_audit']
  self.assertEqual((f['eligible_count'],f['comparable_count'],f['matched_count'],f['missing_actual_count'],f['missing_comparison_count']),(4,3,1,1,1))
  self.assertAlmostEqual(f['percentage'],100/3)
  self.assertEqual(r['data'][0]['Late Count'],1)
  condition={k:v for k,v in DATE_PARAMS.items() if k not in {'filters','matched_label'}}
  self.assertEqual(len(filter_data(df,[condition])),2)
  with self.assertRaisesRegex(ValueError,'value_column'):filter_data(df,[{'column':'actual','operator':'>','value':'estimate','value_type':'date'}])
  with self.assertRaises(ValueError):filter_data(df,[{**condition,'value':'2020-01-01'}])
  with self.assertRaises(ValueError):calculate(df,{**DATE_PARAMS,'value_column':'missing'})
  with self.assertRaisesRegex(ValueError,'denominator'):calculate(df,{**DATE_PARAMS,'filters':[condition]})
  empty=calculate(df.iloc[:0],DATE_PARAMS)
  self.assertIsNone(empty['comparison_audit']['percentage'])

class OlistResultTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.path=Path(DatasetManager.get_dataset(None,'olist.db::orders').filepath)
 def test_independent_olist_counts_categories_payments_and_dates(self):
  orders=DatasetManager.load_dataset_dataframe(DatasetManager.get_dataset(None,'olist.db::orders'))
  r=AnalysisEngine.execute_plan(None,'t',{'aggregation':{'group_by':['order_status'],'aggregations':{'order_id':'count'}}},dataframe=orders)
  self.assertEqual(sum(row['Order Count'] for row in r['data']),99441)
  key={'from_table':'olist.db::order_items','from_column':'product_id','to_table':'olist.db::products','to_column':'product_id'}
  frame=DatasetManager.load_joined_dataframe(['olist.db::order_items','olist.db::products'],[key])
  params={'group_by':['product_category_name'],'aggregations':{'price_cents':'sum'},'transforms':[{'column':'price_cents','divide_by':100,'as':'Price (BRL)','unit':'BRL'}],'fill_missing':{'product_category_name':'Unknown'}}
  category=AnalysisEngine.execute_plan(None,'t',{'aggregation':params},dataframe=frame)
  with sqlite3.connect(self.path) as db:
   expected=db.execute('SELECT COALESCE(p.product_category_name,\'Unknown\'),SUM(i.price_cents)/100.0 FROM order_items i JOIN products p ON i.product_id=p.product_id GROUP BY 1').fetchall()
   counts=dict(db.execute('SELECT order_status,COUNT(order_id) FROM orders GROUP BY 1'))
   dates=db.execute("SELECT COUNT(*),SUM(date(order_delivered_customer_date)>date(order_estimated_delivery_date)) FROM orders WHERE order_status='delivered' AND order_delivered_customer_date IS NOT NULL AND order_estimated_delivery_date IS NOT NULL").fetchone()
  self.assertEqual({row['order_status']:row['Order Count'] for row in r['data']},counts)
  actual={row['product_category_name']:row['Price (BRL)'] for row in category['data']}
  self.assertEqual(set(actual),set(dict(expected)))
  for name,value in expected:self.assertAlmostEqual(actual[name],value,places=5)
  top_params={'group_by':['product_category_name'],'aggregations':{'price_cents':'sum'},'transforms':[{'column':'price_cents','divide_by':100,'as':'Price (BRL)','unit':'BRL'}],'fill_missing':{'product_category_name':'Unknown'},'limit':10,'sort_by':'price_cents','ascending':False}
  top=AnalysisEngine.execute_plan(None,'t',{'aggregation':top_params},dataframe=frame)
  self.assertEqual(top['row_count'],10)
  self.assertEqual([(r['product_category_name'],r['Price (BRL)']) for r in top['data']],sorted(expected,key=lambda r:(-r[1],r[0]))[:10])
  payment_frame=DatasetManager.load_dataset_dataframe(DatasetManager.get_dataset(None,'olist.db::order_payments'))
  params={'group_by':['payment_type'],'aggregations':{'payment_value_cents':'sum'},'transforms':[{'column':'payment_value_cents','divide_by':100,'as':'Payment Value (BRL)','unit':'BRL'}]}
  payment=AnalysisEngine.execute_plan(None,'t',{'aggregation':params},dataframe=payment_frame)
  credit=next(row for row in payment['data'] if row['payment_type']=='credit_card')
  self.assertEqual(credit['Payment Value (BRL)'],12542084.19)
  p={**DATE_PARAMS,'column':'order_delivered_customer_date','value_column':'order_estimated_delivery_date','filters':[{'column':'order_status','operator':'==','value':'delivered'}]}
  late=calculate(orders,p)['comparison_audit']
  self.assertEqual((late['comparable_count'],late['matched_count']),dates)
  self.assertEqual((late['eligible_count'],late['matched_count'],late['missing_actual_count']),(96470,6534,8))
 def test_fresh_results_and_reopened_snapshots_share_transformed_values(self):
  engine=create_engine('sqlite://');Base.metadata.create_all(engine)
  with Session(engine) as db:
   db.add(DBProject(id='test',name='Test'));db.commit()
   cases=[('olist.db::orders','Count order_id by order_status.','aggregation',{'group_by':['order_status'],'aggregations':{'order_id':'count'}}),
    ('olist.db::order_payments','Show payment totals in BRL dividing payment_value_cents by 100.','aggregation',{'group_by':['payment_type'],'aggregations':{'payment_value_cents':'sum'}}),
    ('olist.db::order_items','Return top 10 categories by sales in BRL with missing categories as Unknown.','aggregation',{'group_by':['product_category_name'],'aggregations':{'price_cents':'sum'}}),
    ('olist.db::orders','What percentage of delivered orders arrived after the estimated date, comparing calendar dates?','comparison_summary',{'column':'order_delivered_customer_date','value_column':'order_estimated_delivery_date','operator':'>','value_type':'date','date_part':'date','matched_label':'Late','filters':[{'column':'order_status','operator':'==','value':'delivered'}]})]
   for dataset,question,tool,params in cases:
    replies=[json.dumps({'action':'tool_call','tool':tool,'parameters':params}),json.dumps({'action':'final_answer','content':'These are still raw cents. The table is unavailable.'})]
    selection={'tables_needed':[dataset]}
    if params.get('group_by')==['product_category_name']:
     selection={'tables_needed':['olist.db::order_items','olist.db::products'],'join_keys':[{'from_table':'olist.db::order_items','from_column':'product_id','to_table':'olist.db::products','to_column':'product_id'}]}
    if tool=='aggregation' and dataset=='olist.db::order_payments':params.update(transforms=[{'column':'payment_value_cents','divide_by':100,'as':'Payment Value (BRL)','unit':'BRL'}])
    if tool=='aggregation' and dataset=='olist.db::order_items':params.update(transforms=[{'column':'price_cents','divide_by':100,'as':'Price (BRL)','unit':'BRL'}],fill_missing={'product_category_name':'Unknown'},limit=10,sort_by='price_cents',ascending=False)
    plan={'intent':'SIMPLE','context_action':'standalone','analysis_plan':{'source':{'tables':selection['tables_needed'],'join_keys':selection.get('join_keys',[])},'outputs':[{'id':'main','kind':tool,'parameters':params}]}}
    with patch('app.api.v1.chat.QueryPlanner.plan_query',return_value=plan),patch('app.llm.table_selector.TableSelector.select_tables',return_value=selection),patch('app.llm.agent.OllamaClient.call_model_chat',side_effect=replies) as model:
     response,failed=process_chat_message(ChatRequest(project_id='test',dataset_id=dataset,message=question),db,lambda stage:None)
    if tool=='comparison_summary':model.assert_not_called()
    self.assertFalse(failed,response);self.assertNotIn('still raw cents',response['content'])
    saved=next(s for s in list_saved_analyses('test',db) if s['id']==response['id'])
    self.assertEqual(saved['result'],response['results'])
    history=list_project_messages('test',None,db)['messages'];stored=next(m for m in history if m['id']==response['id'])
    self.assertEqual(json.loads(stored['metadata_json'])['results'],response['results'])
   db.close()
  engine.dispose()

if __name__=='__main__':unittest.main()
