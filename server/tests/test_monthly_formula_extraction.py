"""Complete expression extraction and captured-response replay; HTTP/model blocked."""
import copy
import json
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.analysis.operations import formula_identity, execute
from app.api.v1.chat import process_chat_message
from app.api.v1.projects import list_saved_analyses
from app.models.chat import ChatRequest, DBChatHistory
from app.models.project import DBProject
from app.services import planned_analysis
from app.services.metadata_service import MetadataService
from app.services.dataset_manager import DatasetManager
from app.services.request_requirements import validate_plan_request, RequestIncomplete
from app.storage.sqlite.session import Base
from app.core.config import settings

EVIDENCE=Path(settings.WORKSPACE_DIR)/'evaluations/monthly-formula-rejection-2026-11-10'
CAPTURE=json.loads((EVIDENCE/'response.json').read_text())
QUESTION=CAPTURE['metadata']['question']
PLAN=CAPTURE['metadata']['planner_diagnostics'][0]['output']
FORMULA=formula_identity(PLAN['analysis_plan']['outputs'][0]['parameters']['metric']['expression'])

class FormulaFixture(unittest.TestCase):
    def setUp(self):
        for target in ['urllib.request.urlopen','urllib.request.OpenerDirector.open']:
            blocker=patch(target,side_effect=AssertionError('External calls blocked'));blocker.start();self.addCleanup(blocker.stop)
        self.profile={**MetadataService.get_profile('northwind.db::Orders'),'dataset_id':'northwind.db::Orders'}
        self.catalog=MetadataService.get_catalog_index()
    def requirement(self,question=QUESTION):return {'outputs':[{'id':'calendar','kind':'calendar_aggregate','parameters':PLAN['analysis_plan']['outputs'][0]['parameters']}]}
    def formula_question(self,expression):
        return QUESTION.replace('SUM(UnitPrice × Quantity × (1 − Discount))',expression)



class MonthlyFormulaPipeline(FormulaFixture):
    def send(self,plan=PLAN,question=QUESTION,stale_history=False):
        engine=create_engine('sqlite://');Base.metadata.create_all(engine)
        with Session(engine) as db:
            db.add(DBProject(id='formula-replay',name='Formula replay'));db.commit()
            if stale_history:
                prior={'source':{'tables':['olist.db::orders'],'join_keys':[]},'outputs':[{'id':'old','kind':'comparison_summary','parameters':{'column':'order_delivered_customer_date','value_column':'order_estimated_delivery_date','operator':'>','group_by':[],'value_type':'date','date_part':'date','eligibility_filters':[{'column':'order_status','operator':'==','value':'delivered'}]}}]}
                db.add(DBChatHistory(id='old-olist',project_id='formula-replay',role='assistant',content='Earlier analysis',metadata_json=json.dumps({'analysis_failed':False,'analysis_context':{'version':1,'plan':prior},'calculation':{'steps':[{'tool':'comparison_summary','status':'succeeded','tables':['olist.db::orders']}]}})));db.commit()
            with patch('app.llm.client.OllamaClient.call_model',return_value=json.dumps(plan)) as model,patch('app.llm.agent.Agent.run',side_effect=AssertionError('No alternate execution path')),patch.object(planned_analysis,'run',wraps=planned_analysis.run) as coordinator:
                result,failed=process_chat_message(ChatRequest(project_id='formula-replay',dataset_id='northwind.db::Orders',message=question),db,lambda stage:None)
            self.assertEqual(model.call_count,1)
            if not failed:
                self.assertEqual(coordinator.call_count,1)
                saved=next(v for v in list_saved_analyses('formula-replay',db) if v['id']==result['id'])
                self.assertEqual(saved['analysisPackage'],result['analysis_package'])
            else:self.assertEqual(coordinator.call_count,0)
        engine.dispose();return result,failed
    def test_exact_captured_reply_completes_with_sqlite_and_no_inherited_state(self):
        result,failed=self.send(stale_history=True);self.assertFalse(failed,result['content'])
        rows=result['results']['data'];self.assertEqual([row['Month'] for row in rows],[f'2021-{m:02d}' for m in range(1,13)])
        path=Path(DatasetManager.get_dataset(None,'northwind.db::Orders').filepath)
        with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
            expected=db.execute('''SELECT strftime('%Y-%m',o.OrderDate),SUM(d.UnitPrice*d.Quantity*(1-d.Discount)) FROM Orders o JOIN "Order Details" d ON o.OrderID=d.OrderID WHERE strftime('%Y',o.OrderDate)='2021' GROUP BY 1 ORDER BY 1''').fetchall()
        for row,(month,value) in zip(rows,expected):self.assertEqual(row['Month'],month);self.assertAlmostEqual(row['Net Sales'],value,places=6)
        self.assertAlmostEqual(sum(row['Net Sales'] for row in rows),41355549.74,places=6)
        self.assertAlmostEqual(rows[0]['Net Sales'],3474864.06,places=6);self.assertAlmostEqual(rows[-1]['Net Sales'],4377795.40,places=6)
        self.assertEqual(result['results'].get('units',{}),{});self.assertEqual(result['analysis_plan']['outputs'][0]['parameters']['filters'],[])
        self.assertTrue(result['analysis_package']['charts'])
        output=Path(settings.WORKSPACE_DIR)/'evaluations/single-specification-2026-11-10'
        (output/'monthly-formula-replay.json').write_text(json.dumps({'question':QUESTION,'model_response_source':str(EVIDENCE/'response.json'),'live_model_calls':0,'sqlite_monthly_rows_match':True,'annual_total':sum(row['Net Sales'] for row in rows),'result':result},indent=2)+'\n')
