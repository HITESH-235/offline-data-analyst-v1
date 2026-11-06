import base64
import json
import sqlite3
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
from app.core.config import settings
from app.llm.agent import Agent
from app.sandbox.runner import SandboxRunner
from app.services.chart_artifacts import artifact_file
from app.services.dataset_manager import DatasetManager

class JoinedPythonContractTest(unittest.TestCase):
 def run_agent(self,replies,tool_results):
  frame=pd.DataFrame({'ProductID':[1,2,3],'CategoryName':['A','A','B'],'UnitPrice':[2.,4.,6.]})
  selection={'tables_needed':['northwind.db::Products','northwind.db::Categories'],'join_keys':[{'from_table':'northwind.db::Products','from_column':'CategoryID','to_table':'northwind.db::Categories','to_column':'CategoryID'}]}
  with patch('app.llm.table_selector.TableSelector.select_tables',return_value=selection),patch('app.llm.agent.DatasetManager.load_joined_dataframe',return_value=frame),patch('app.llm.agent.MetadataService.get_profile',return_value={'columns':list(frame.columns)}),patch('app.llm.agent.OllamaClient.call_model_chat',side_effect=replies) as model,patch('app.llm.agent._execute_tool',side_effect=tool_results) as execute:
   result=Agent.run('Box plot of individual prices','COMPLEX',{},'northwind.db::Products',project_id='test')
  return result,model,execute
 def action(self,code):return json.dumps({'action':'tool_call','tool':'run_code','parameters':{'code':code}})
 def test_identical_failed_code_is_not_executed_again(self):
  result,model,execute=self.run_agent([self.action('bad()'),self.action('# Same code with a comment\nbad( )')],[('Unknown column CategoryName',None)])
  self.assertTrue(result['failed']);self.assertEqual(execute.call_count,1);self.assertEqual(model.call_count,2)
  self.assertTrue(result['calculation']['steps'][-1]['execution_skipped'])
 def test_corrected_retry_can_execute(self):
  result,model,execute=self.run_agent([self.action('bad()'),self.action("fig=px.box(df,x='CategoryName',y='UnitPrice')"),json.dumps({'action':'final_answer','content':'Done'})],[('Unknown column',None),('Success',{'artifacts':[]})])
  self.assertFalse(result.get('failed',False));self.assertEqual(execute.call_count,2)
  self.assertTrue(any('exact supplied schema' in message['content'] for message in model.call_args_list[1].args[0]))
 def test_prompt_describes_actual_joined_dataframe(self):
  result,model,execute=self.run_agent([self.action("fig=px.box(df,x='CategoryName',y='UnitPrice')"),json.dumps({'action':'final_answer','content':'Done'})],[('Success',{'artifacts':[]})])
  prompt=model.call_args_list[0].args[0][0]['content']
  self.assertIn('ALREADY BEEN JOINED',prompt);self.assertIn('Input rows: 3',prompt)
  self.assertIn('CategoryName',prompt);self.assertIn('Do not join them again',prompt)

class NorthwindProductBoxTest(unittest.TestCase):
 def test_real_join_and_sandbox_box_preserve_77_observations(self):
  tables=['northwind.db::Products','northwind.db::Categories']
  frame=DatasetManager.load_joined_dataframe(tables,[{'from_table':tables[0],'from_column':'CategoryID','to_table':tables[1],'to_column':'CategoryID'}])
  with sqlite3.connect(f'file:{Path(settings.DATASETS_DIR)/"northwind.db"}?mode=ro',uri=True) as db:
   expected=db.execute('SELECT p.ProductID,c.CategoryName,p.UnitPrice FROM Products p JOIN Categories c ON p.CategoryID=c.CategoryID ORDER BY p.ProductID').fetchall()
  self.assertEqual(len(frame),77);self.assertEqual(frame['ProductID'].nunique(),77)
  self.assertEqual(sorted(frame[['ProductID','CategoryName','UnitPrice']].itertuples(index=False,name=None)),expected)
  with tempfile.TemporaryDirectory() as directory,patch.object(settings,'WORKSPACE_DIR',directory):
   run=SandboxRunner.run_code(tables[0],"fig=px.box(df,x='CategoryName',y='UnitPrice',title='Individual product prices by category')",'test',dataframe=frame)
   try:
    self.assertTrue(run['success'],run.get('error'))
    path,_=artifact_file('test',run['artifacts'][0]['id'],'figure');figure=json.loads(path.read_text())
    observed=[]
    for trace in figure['data']:
     prices=trace['y']
     if isinstance(prices,dict):prices=np.frombuffer(base64.b64decode(prices['bdata']),dtype=prices['dtype']).tolist()
     observed.extend(zip(trace['x'],prices))
    self.assertEqual(len(observed),77)
    self.assertEqual(Counter(observed),Counter((category,price) for _,category,price in expected))
   finally:SandboxRunner.cleanup(run)
