"""Context isolation with exact captured planner reply; no live calls."""
import copy
import json
import sqlite3
from pathlib import Path
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
import test_entity_comparison as staged
from app.services.analysis_context import load_context


CAPTURE=json.loads((Path(__file__).parent/'fixtures/standalone_financial_context_failure.json').read_text())
QUESTION=CAPTURE['metadata']['question']
DRAFT=CAPTURE['metadata']['planner_diagnostics'][0]['output']
ROOT=Path('/app/workspace/evaluations/single-specification-2026-11-10')
SQL='''SELECT c.customer_state,SUM(f.payment_total_cents)/100.0 AS paid FROM order_financials f JOIN orders o ON f.order_id=o.order_id JOIN customers c ON o.customer_id=c.customer_id WHERE f.has_payments=1 AND date(o.order_purchase_timestamp) BETWEEN '2018-01-01' AND '2018-12-31' GROUP BY c.customer_state ORDER BY paid DESC'''

class StandaloneRequirements(staged.OfflineTest):
    def setUp(self):
        super().setUp();self.engine=create_engine('sqlite://');staged.Base.metadata.create_all(self.engine);self.db=Session(self.engine)
        self.db.add(staged.DBProject(id='staged',name='Standalone replay'));self.db.commit()
        self.profile={**staged.MetadataService.get_profile('olist.db::orders'),'dataset_id':'olist.db::orders'}
        self.catalog=staged.MetadataService.get_catalog_index()
        self.history={'recent_successes':[{'message_id':'baseline','analysis':{'version':1,'plan':staged.PLAN['analysis_plan']}}]}
    def tearDown(self):self.db.close();self.engine.dispose()
    def send(self,plan=staged.PLAN,question=staged.QUESTION):
        with patch('app.llm.client.OllamaClient.call_model',return_value=json.dumps(plan)) as model,patch('app.llm.agent.Agent.run',side_effect=AssertionError('No alternate route')):
            result,failed=staged.process_chat_message(staged.ChatRequest(project_id='staged',dataset_id='olist.db::orders',message=question),self.db,lambda s:None)
        self.assertEqual(model.call_count,1)
        return result,failed
    def test_captured_payment_after_staged_baseline_matches_every_sqlite_state(self):
        baseline,failed=self.send();self.assertFalse(failed,baseline['content'])
        self.db.close();self.db=Session(self.engine)
        r,failed=self.send(DRAFT,QUESTION);self.assertFalse(failed,r['content'])
        self.assertIsNone(r['analysis_package']['request_requirements'])
        self.assertEqual(r['analysis_status'],'complete')
        rows=r['results']['data'];self.assertEqual(len(rows),27)
        path=Path(staged.DatasetManager.get_dataset(None,'olist.db::orders').filepath)
        with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:oracle=db.execute(SQL).fetchall()
        self.assertEqual([row['customer_state'] for row in rows],[row[0] for row in oracle])
        for row,(state,expected) in zip(rows,oracle):self.assertAlmostEqual(row['Paid Amount (BRL)'],expected,places=6)
        actual={row['customer_state']:row['Paid Amount (BRL)'] for row in rows}
        self.assertAlmostEqual(sum(actual.values()),8699763.05,places=6)
        for state,total in [('SP',3419478.51),('RJ',1075017.63),('MG',1011722.65)]:self.assertAlmostEqual(actual[state],total,places=6)
        ROOT.mkdir(parents=True,exist_ok=True)
        (ROOT/'payment-replay.json').write_text(json.dumps({'live_model_calls':0,'sql':SQL,'oracle':oracle,'result':r},indent=2)+'\n')
