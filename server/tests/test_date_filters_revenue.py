import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.analysis.filtering import filter_data
from app.analysis.monthly_revenue import calculate_monthly_revenue
from app.analysis_engine import AnalysisEngine
from app.llm.agent import _execute_tool, _summarize_results
from app.core.config import settings
from app.storage.sqlite.session import Base
from app.models.project import DBProject
from app.models.chat import ChatRequest
from app.api.v1.chat import process_chat_message, handle_chat_message
from app.api.v1.projects import list_saved_analyses
from app.services.dataset_manager import DatasetManager

PARAMS={'year':2022,'date_column':'OrderDate','unit_price_column':'UnitPrice','quantity_column':'Quantity','discount_column':'Discount'}
FILTERS=[{'column':'OrderDate','operator':'>=','value':'2022-01-01'},{'column':'OrderDate','operator':'<','value':'2023-01-01'}]

class DateFilterTest(unittest.TestCase):
 def setUp(self):
  self.df=pd.DataFrame({'OrderDate':['2016-07-04','2022-01-01','2022-12-31 23:59:59','2023-01-01'], 'Quantity':[1,2,3,4]})
 def test_exact_emitted_filter_is_applied_instead_of_skipped(self):
  emitted=[{'column':'OrderDate','operator':'>=','value':'2022-01-01'},{'column':'OrderDate','operator':'<=','value':'2022-12-31'}]
  result=filter_data(self.df,emitted)
  self.assertEqual(result['Quantity'].tolist(),[2])
  self.assertEqual(filter_data(self.df,FILTERS)['Quantity'].tolist(),[2,3])
 def test_invalid_filters_fail_even_on_empty_input(self):
  invalid=[[],None,{},'not a list',[{}],[{'column':'missing','operator':'==','value':1}],
   [{'column':'Quantity','operator':'between','value':[1,4]}],[{'column':'Quantity','operator':'>','value':'two'}],
   [{'column':'Quantity','operator':'in','value':3}],[{'column':'OrderDate','operator':'>','value':'2022-40-01'}],
   [{'column':'OrderDate','operator':'>','value':'Jan 2022'}],
   [{'column':'OrderDate','operator':'>=','value':'2022-01-01','unexpected':'ignored?'}]]
  for frame in [self.df,self.df.iloc[:0]]:
   for predicates in invalid:
    with self.subTest(predicates=predicates,empty=frame.empty),self.assertRaises(ValueError):filter_data(frame,predicates)
 def test_bad_source_dates_are_not_silently_dropped(self):
  df=self.df.copy();df.loc[0,'OrderDate']='not-a-date'
  with self.assertRaises(ValueError):filter_data(df,FILTERS)
 def test_every_predicate_is_validated_even_when_first_returns_no_rows(self):
  with self.assertRaises(ValueError):filter_data(self.df,[{'column':'Quantity','operator':'>','value':999},{'column':'unknown','operator':'==','value':1}])
 def test_unchanged_valid_filter_is_audited_and_is_not_evidence_of_absent_year(self):
  result=AnalysisEngine.execute_plan(None,'test',{'filters':[{'column':'Quantity','operator':'>','value':0}]},dataframe=self.df)
  self.assertTrue(result['filter_audit']['unchanged']);self.assertEqual(result['filter_audit']['matched_row_count'],4)
  observation=_summarize_results(result)
  self.assertIn('NOT evidence',observation);self.assertIn('NOT exhaustive',observation)
 def test_malformed_outer_tool_parameters_return_error_without_rows(self):
  for params in [{},{'filters':FILTERS,'year':2022},{'conditions':FILTERS},{'filters':[{'column':'OrderDate','operator':'year','value':2022}]}]:
   observation,result=_execute_tool('filtering',params,'test',None,{},dataframe=self.df)
   self.assertIsNone(result);self.assertIn('failed',observation)
 def test_numeric_and_literal_contains_filters_remain_valid(self):
  self.assertEqual(filter_data(self.df,[{'column':'Quantity','operator':'>','value':2}])['Quantity'].tolist(),[3,4])
  self.assertEqual(len(filter_data(pd.DataFrame({'Name':['a.b','axb']}),[{'column':'Name','operator':'contains','value':'.'}])),1)

class RevenueFixtureTest(unittest.TestCase):
 def setUp(self):
  self.df=pd.DataFrame({'OrderDate':['2022-01-01','2022-01-31 12:00:00','2022-12-31 23:59:59','2023-01-01'],
   'UnitPrice':[10.,20.,5.,999.],'Quantity':[2,3,4,100],'Discount':[.1,0.,.5,0.]})
 def test_formula_months_end_of_year_and_total(self):
  result=calculate_monthly_revenue(self.df,PARAMS)
  self.assertEqual(result['data'],[{'Month':'2022-01','Revenue':78.},{'Month':'2022-12','Revenue':10.}])
  self.assertEqual(result['verification']['total_revenue'],88.)
  self.assertEqual(result['verification']['matched_row_count'],3)
 def test_invalid_measure_dates_and_parameters_fail(self):
  for column,value in [('Discount',2.),('UnitPrice',None),('Quantity',float('inf')),('OrderDate','bad-date')]:
   df=self.df.copy();df[column]=df[column].astype(object);df.loc[0,column]=value
   with self.subTest(column=column),self.assertRaises(ValueError):calculate_monthly_revenue(df,PARAMS)
  for params in [{**PARAMS,'year':'2022'},{**PARAMS,'unit_price_column':'SUM(UnitPrice)'},{**PARAMS,'foo':'bar'}]:
   with self.assertRaises(ValueError):calculate_monthly_revenue(self.df,params)
 def test_empty_year_is_verified_from_full_data_not_preview(self):
  result=calculate_monthly_revenue(self.df,{**PARAMS,'year':2020})
  self.assertEqual(result['data'],[]);self.assertEqual(result['verification']['matched_row_count'],0)

class MonthlyAnswerValidationTest(unittest.TestCase):
 def test_noncanonical_monthly_question_cannot_finish_with_raw_filter_rows(self):
  from app.llm.agent import Agent
  question='I need monthly revenue for 2022, please.'
  actions=[json.dumps({'action':'tool_call','tool':'filtering','parameters':{'filters':FILTERS}}),json.dumps({'action':'final_answer','content':'No records for 2022 exist'})]
  raw={'columns':['OrderDate','UnitPrice'],'data':[{'OrderDate':'2022-01-01','UnitPrice':10}],'row_count':1}
  with patch('app.llm.table_selector.TableSelector.select_tables',return_value={'tables_needed':['fixture.csv']}),patch('app.llm.agent.MetadataService.get_profile',return_value={'columns':['OrderDate','UnitPrice']}),patch('app.llm.agent.OllamaClient.call_model_chat',side_effect=actions),patch('app.llm.agent._execute_tool',return_value=('Rows returned',raw)):
   response=Agent.run(question,'SIMPLE',{},'fixture.csv')
  self.assertTrue(response['failed']);self.assertNotIn('results',response);self.assertNotIn('No records',response['content'])
 def test_monthly_tool_explanation_cannot_be_overwritten_by_model(self):
  from app.llm.agent import Agent
  fixture=RevenueFixtureTest();fixture.setUp();result=calculate_monthly_revenue(fixture.df,PARAMS)
  actions=[json.dumps({'action':'tool_call','tool':'monthly_revenue','parameters':PARAMS}),json.dumps({'action':'final_answer','content':'No 2022 records exist'})]
  with patch('app.llm.table_selector.TableSelector.select_tables',return_value={'tables_needed':['fixture.csv']}),patch('app.llm.agent.MetadataService.get_profile',return_value={'columns':list(fixture.df.columns)}),patch('app.llm.agent.OllamaClient.call_model_chat',side_effect=actions),patch('app.llm.agent._execute_tool',return_value=('Verified result',result)):
   response=Agent.run('I need monthly revenue for 2022, please.','SIMPLE',{},'fixture.csv')
  self.assertNotIn('No 2022',response['content']);self.assertIn('2 calendar months',response['content']);self.assertEqual(response['results']['data'],result['data'])

class NorthwindMonthlyRevenueTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.tables=['northwind.db::Orders','northwind.db::Order Details']
  cls.keys=[{'from_table':cls.tables[1],'from_column':'OrderID','to_table':cls.tables[0],'to_column':'OrderID'}]
  cls.frame=DatasetManager.load_joined_dataframe(cls.tables,cls.keys)
  path=Path(DatasetManager.get_dataset(None,cls.tables[0]).filepath).resolve()
  with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
   cls.expected=db.execute("SELECT strftime('%Y-%m',o.OrderDate),SUM(d.UnitPrice*d.Quantity*(1-d.Discount)) FROM Orders o JOIN \"Order Details\" d ON o.OrderID=d.OrderID WHERE o.OrderDate >= '2022-01-01' AND o.OrderDate < '2023-01-01' GROUP BY 1 ORDER BY 1").fetchall()
   cls.orders_2022=db.execute("SELECT COUNT(*) FROM Orders WHERE strftime('%Y',OrderDate)='2022'").fetchone()[0]
 def compare(self,result):
  self.assertEqual(result['columns'],['Month','Revenue']);self.assertEqual(result['row_count'],12)
  self.assertEqual([row['Month'] for row in result['data']],[month for month,_ in self.expected])
  for actual,(_,expected) in zip(result['data'],self.expected):self.assertAlmostEqual(actual['Revenue'],expected,places=5)
  self.assertAlmostEqual(result['verification']['total_revenue'],sum(value for _,value in self.expected),places=5)
  self.assertEqual(result['visualization_blueprint']['chart_type'],'line')
 def test_running_database_and_full_app_calculation_match_sql(self):
  self.assertEqual(self.orders_2022,1352);self.assertEqual(len(self.frame),609283)
  result=AnalysisEngine.execute_plan(None,self.tables[0],{'monthly_revenue':PARAMS},dataframe=self.frame)
  self.compare(result)
 def test_original_filters_no_longer_return_the_full_join(self):
  filtered=filter_data(self.frame,[{'column':'OrderDate','operator':'>=','value':'2022-01-01'}, {'column':'OrderDate','operator':'<=','value':'2022-12-31'}])
  self.assertGreater(len(filtered),0);self.assertLess(len(filtered),609283)
  self.assertTrue(pd.to_datetime(filtered['OrderDate'],format='mixed').dt.year.eq(2022).all())
 def test_original_question_json_and_saved_result_cannot_be_replaced_by_false_model_claim(self):
  engine=create_engine('sqlite://');Base.metadata.create_all(engine)
  with Session(engine) as db:
   db.add(DBProject(id='test',name='Test'));db.commit()
   request=ChatRequest(project_id='test',dataset_id=self.tables[0],message='show monthly revenue for year 2022')
   with patch('app.api.v1.chat.QueryPlanner.plan_query') as planner,patch('app.llm.table_selector.TableSelector.select_tables',return_value={'tables_needed':self.tables,'join_keys':self.keys}),patch('app.llm.agent.DatasetManager.load_joined_dataframe',return_value=self.frame),patch('app.llm.agent.OllamaClient.call_model_chat',return_value=json.dumps({'action':'final_answer','content':'No 2022 records exist'})) as model:
    response=handle_chat_message(request,db)
   self.compare(response['results']);planner.assert_not_called();model.assert_not_called()
   self.assertNotIn('No 2022',response['content']);self.assertIn('12 calendar months',response['content'])
   saved=list_saved_analyses('test',db);self.assertEqual(len(saved),1);self.compare(saved[0]['result'])
   self.assertEqual(saved[0]['tables'],self.tables)
  engine.dispose()
