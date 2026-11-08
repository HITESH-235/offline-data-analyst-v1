"""Controlled regression cases; no provider calls are made by these tests."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from app.analysis.chart_consistency import (
    order_total_expectation, order_total_explanation, population_summary,
    validate_captures, wants_order_total_histogram,
)
from app.core.config import settings
from app.llm.agent import Agent
from app.sandbox.runner import SandboxRunner


def lines():
    return pd.DataFrame({'OrderID':[1,1,2], 'UnitPrice':[10.,20.,30.],
                         'Quantity':[1,2,1], 'Discount':[0.,.5,0.]})


class ChartPopulationTest(unittest.TestCase):
    def test_order_grain_and_formula(self):
        expected=order_total_expectation(lines())
        self.assertEqual(expected['count'],2)
        self.assertEqual(expected['input_line_count'],3)
        self.assertEqual(expected['total'],60.)
        self.assertEqual(expected['fingerprint'],population_summary([30.,30.])['fingerprint'])
        self.assertIn('2 order totals from 3 line items',order_total_explanation(expected))

    def test_renaming_line_item_histogram_does_not_make_it_valid(self):
        capture={'status':'ready','title':'Individual order totals',
                 'observations':[population_summary([10.,20.,30.])]}
        with self.assertRaisesRegex(ValueError,'plotted 3 observations.*2 aggregated orders'):
            validate_captures([capture],order_total_expectation(lines()))
        self.assertNotIn('population',capture)

    def test_count_alone_is_insufficient(self):
        capture={'status':'ready','observations':[population_summary([10.,50.])]}
        with self.assertRaisesRegex(ValueError,'population mismatch'):
            validate_captures([capture],order_total_expectation(lines()))

    def test_two_axes_can_show_same_verified_population(self):
        expected=order_total_expectation(lines())
        capture={'status':'ready','observations':[population_summary([30.,30.])]*2}
        validate_captures([capture],expected)
        self.assertTrue(capture['population']['verified'])

    def test_weighted_or_unverifiable_charts_are_rejected(self):
        expected=order_total_expectation(lines())
        for capture in [dict(status='ready'),dict(status='empty'),
                        dict(status='ready',observations=[{**population_summary([30.,30.]),'weighted':True}])]:
            with self.assertRaises(ValueError):validate_captures([capture],expected)

    def test_empty_or_invalid_input_fails_explicitly(self):
        for frame in [lines().iloc[:0],lines().drop(columns='OrderID'),lines().assign(Discount=2.)]:
            with self.assertRaises(ValueError):order_total_expectation(frame)
        self.assertTrue(wants_order_total_histogram('Show a histogram of individual order totals after discounts.'))
        self.assertFalse(wants_order_total_histogram('Show a histogram of order line totals after discounts.'))


class SandboxPopulationTest(unittest.TestCase):
    def test_actual_capture_rejects_line_items_and_accepts_order_totals(self):
        frame=lines()
        expected=order_total_expectation(frame)
        base="df['net']=df['UnitPrice']*df['Quantity']*(1-df['Discount'])\n"
        with tempfile.TemporaryDirectory() as directory,patch.object(settings,'WORKSPACE_DIR',directory):
            bad=SandboxRunner.run_code('fixture',base+"plt.hist(df['net'])",'test',dataframe=frame,chart_expectation=expected)
            try:
                self.assertFalse(bad['success'])
                self.assertEqual(bad['artifacts'],[])
                self.assertIn('3 observations',bad['error'])
            finally:SandboxRunner.cleanup(bad)
            for code in ["plt.hist(df.groupby('OrderID')['net'].sum())\nplt.close('all')",
                         "fig=px.histogram(df.groupby('OrderID',as_index=False)['net'].sum(),x='net')"]:
                good=SandboxRunner.run_code('fixture',base+code,'test',dataframe=frame,chart_expectation=expected)
                try:
                    self.assertTrue(good['success'],good.get('error'))
                    self.assertTrue(good['artifacts'][0]['population']['verified'])
                    self.assertEqual(good['artifacts'][0]['population']['count'],2)
                finally:SandboxRunner.cleanup(good)


class FinalChartSetTest(unittest.TestCase):
    def action(self,code):
        return json.dumps({'action':'tool_call','tool':'run_code','parameters':{'code':code}})

    def test_multiple_verified_exports_remain_accessible_and_narrative_is_grounded(self):
        frame=lines()
        population={**order_total_expectation(frame),'verified':True}
        first={'id':'a'*32,'population':population}
        second={'id':'b'*32,'population':population}
        replies=[self.action('first()'),self.action('corrected()'),json.dumps({'action':'final_answer','content':'There are 999 orders'})]
        with tempfile.TemporaryDirectory() as directory,patch.object(settings,'WORKSPACE_DIR',directory):
            folder=Path(directory)/'projects'/'test'/'charts'
            folder.mkdir(parents=True)
            stale=folder/(first['id']+'-download.png');stale.write_bytes(b'old')
            with patch('app.llm.table_selector.TableSelector.select_tables',return_value={'tables_needed':['fixture::Details']}), \
                 patch('app.llm.agent.DatasetManager.load_joined_dataframe',return_value=frame), \
                 patch('app.llm.agent.MetadataService.get_profile',return_value={'columns':list(frame.columns)}), \
                 patch('app.llm.agent.OllamaClient.call_model_chat',side_effect=replies), \
                 patch('app.llm.agent._execute_tool',side_effect=[('ok',{'artifacts':[first]}),('ok',{'artifacts':[second]})]):
                result=Agent.run('Show a histogram of individual order totals after discounts.','COMPLEX',{},'fixture::Details',project_id='test')
            self.assertFalse(result.get('failed',False))
            self.assertEqual(result['artifacts'],[first,second])
            self.assertNotIn('superseded',result['calculation']['steps'][0])
            self.assertEqual(second['provenance']['step_index'],1)
            self.assertNotIn('999',result['content'])
            self.assertIn('2 order totals from 3 line items',result['content'])
            self.assertTrue(stale.exists())


if __name__=='__main__':unittest.main()
