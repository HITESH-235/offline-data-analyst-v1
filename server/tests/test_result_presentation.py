"""Presentation decisions cannot alter verified values or completion checks."""
import copy,unittest
import pandas as pd
from app.analysis.operations import execute,output_contract
from app.services.analysis_package import OutputAccumulator,finalize

class ResultPresentation(unittest.TestCase):
    def publish(self,outputs,frame,presentation=None,chart=False):
        plan={'source':{'tables':['fixture']},'outputs':outputs,'presentation':presentation or {},'chart_scope':{'required':chart}}
        contract=output_contract(plan);a=OutputAccumulator()
        for out in outputs:a.record(out['kind'],out['parameters'],execute(out['kind'],out['parameters'],frame),plan['source'],0,out['id'],contract)
        return finalize({'analysis_outputs':a.export(),'analysis_plan':plan},'Calculate','p','r',contract)
    def counts(self):
        return [{'id':name,'kind':'aggregation','parameters':{'measures':[{'id':'orders','column':'id','operation':'count','label':name}],'filters':filters}} for name,filters in [('Total',[]),('With',[{'column':'paid','operator':'==','value':1}]),('Without',[{'column':'paid','operator':'==','value':0}])]]
    def test_three_count_audit_stays_in_chat_but_retains_every_verified_table(self):
        r=self.publish(self.counts(),pd.DataFrame({'id':[1,2,3],'paid':[1,1,0]}));p=r['analysis_package']
        self.assertEqual(r['analysis_status'],'complete');self.assertTrue(r['scalar_answer'])
        self.assertEqual(len(p['tables']),3);self.assertEqual(p['charts'],[])
        self.assertFalse(p['presentation']['has_detail']);self.assertNotIn('Open result',r['content']);self.assertNotIn('|',r['content'])
        self.assertTrue(all(c['status']=='passed' for c in p['completion_checks']))
        self.assertEqual([next(iter(t['result']['data'][0].values())) for t in p['tables']],[3,2,1])
    def test_explicit_scalar_tables_are_honored(self):
        for presentation in [{'table_requested':True},{'table_in_chat':True}]:
            r=self.publish(self.counts(),pd.DataFrame({'id':[1,2],'paid':[1,0]}),presentation)
            self.assertTrue(r['analysis_package']['presentation']['has_detail']);self.assertNotIn('scalar_answer',r)
            if presentation.get('table_in_chat'):self.assertIn('| Total |',r['content'])
    def test_single_group_ranking_and_monthly_trend_keep_detail(self):
        grouped={'id':'rank','kind':'aggregation','parameters':{'group_by':['region'],'measures':[{'id':'sales','column':'value','operation':'sum','label':'Sales'}]}}
        for regions in [['A'],['A','B','C']]:
            r=self.publish([grouped],pd.DataFrame({'region':regions,'value':[1]*len(regions)}))
            self.assertTrue(r['analysis_package']['presentation']['has_detail']);self.assertTrue(r['analysis_package']['charts'])
        month={'id':'month','kind':'calendar_aggregate','parameters':{'date_column':'day','years':[2021],'grain':'month','metric':{'name':'Sales','aggregation':'sum','expression':{'column':'value'}}}}
        r=self.publish([month],pd.DataFrame({'day':['2021-01-01'],'value':[12]}))
        self.assertEqual(len(r['results']['data']),12);self.assertTrue(r['analysis_package']['charts']);self.assertTrue(r['analysis_package']['presentation']['has_detail'])
    def test_explicit_chart_requirement_is_not_dropped_for_scalar(self):
        r=self.publish(self.counts()[:1],pd.DataFrame({'id':[1],'paid':[1]}),chart=True)
        self.assertEqual(r['analysis_status'],'incomplete');self.assertIn('requested chart',r['content'])
        self.assertTrue(r['analysis_package']['chart_scope']['preference']=='required')
        # A scalar cannot silently clear an inherited chart requirement. This
        # protects the earlier corrected follow-up fixture's intended behavior.
    def test_mean_comparison_keeps_its_table_even_for_two_rows(self):
        p={'column':'actual','value_column':'target','operator':'>','group_by':['region']}
        r=self.publish([{'id':'comparison','kind':'comparison_summary','parameters':p}],pd.DataFrame({'actual':[1,0],'target':[0,0],'region':['A','B']}))
        self.assertTrue(r['analysis_package']['presentation']['has_detail']);self.assertIn('Open result',r['content'])
