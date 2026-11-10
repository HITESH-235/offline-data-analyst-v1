import copy
import unittest
import pandas as pd
from app.analysis.operations import execute, stamp, guard_repair, ContractError
from app.services.analysis_package import OutputAccumulator, finalize
from app.services.answer_summary import comparison_summary
from app.services.request_requirements import publication_checks


class AnswerPresentationTest(unittest.TestCase):
    def publish(self,kind,p,frame,question='Analyze this result.',request=None):
        r=execute(kind,p,frame)
        contract={'outputs':[{'id':'calculated','kind':kind,'parameters':p}]}
        a=OutputAccumulator();a.record(kind,p,r,{'tables':['fixture'],'join_keys':[]},0,'calculated',contract)
        return finalize({'analysis_outputs':a.export()},question,'test','reply',contract,request_requirements=request)
    def test_single_scalar_stays_in_chat_and_does_not_invent_chart(self):
        r=self.publish('aggregation',{'group_by':[],'aggregations':{'value':'sum'}},pd.DataFrame({'value':[3,4]}))
        self.assertEqual(r['analysis_status'],'complete');self.assertTrue(r['scalar_answer'])
        self.assertIn('value: 7',r['content']);self.assertNotIn('|',r['content'])
        self.assertEqual(r['analysis_package']['charts'],[])
        self.assertNotIn('chart',r['content'].lower())
    def test_comparison_answer_has_a_lead_rankings_and_short_data_notes(self):
        p={'column':'actual','value_column':'target','operator':'>','group_by':['region'],
           'matched_label':'Late','count_label':'Orders','sort_by':'percentage'}
        r=self.publish('comparison_summary',p,pd.DataFrame({'region':['A','B','C'],'actual':[1.,0.,float('nan')],'target':[0.,0.,0.]}))
        text=r['content']
        self.assertTrue(text.startswith('**Overall late rate: 50.000000%**'))
        self.assertIn('**1 of 2** comparable orders was late.',text)
        self.assertIn('**Highest late rates**\n\n- **A:** 100.000000%',text)
        self.assertIn('**Data notes**\n\n- **1 order** is missing',text)
        self.assertEqual(text.count('**Open result**'),1)
        self.assertNotIn('|',text)
    def test_incomplete_answer_separates_missing_requirements_from_verified_facts(self):
        p={'group_by':['region'],'aggregations':{'value':'sum'}}
        req={'outputs':[{'id':'user','kind':'aggregation','parameters':p,'columns':['Missing rate']}]}
        r=self.publish('aggregation',p,pd.DataFrame({'region':['a','b'],'value':[3,4]}),request=req)
        self.assertIn('**Analysis incomplete**',r['content'])
        self.assertIn('**What is missing**',r['content'])
        self.assertIn('**Verified findings**',r['content'])
        self.assertLess(r['content'].index('**What is missing**'),r['content'].index('**Verified findings**'))

    def test_requested_columns_and_units_are_not_ignored_when_parameters_also_exist(self):
        p={'group_by':['region'],'aggregations':{'value':'sum'}}
        req={'outputs':[{'id':'user','kind':'aggregation','parameters':p,'columns':['Missing rate']}]}
        r=self.publish('aggregation',p,pd.DataFrame({'region':['a','b'],'value':[3,4]}),request=req)
        self.assertEqual(r['analysis_status'],'incomplete');self.assertNotIn('|',r['content'])
    def test_weighted_overall_rate_not_mean_of_group_rates(self):
        p={'column':'actual','value_column':'target','operator':'>','group_by':['region'],'sort_by':'percentage'}
        df=pd.DataFrame({'region':['a']*100+['b'],'actual':[1]+[0]*99+[1],'target':[0]*101})
        r=execute('comparison_summary',p,df);summary=comparison_summary(r)
        self.assertIn('1.980198%',summary);self.assertNotIn('50.5',summary)
    def test_null_only_percentages_have_no_fabricated_percentage_chart(self):
        p={'column':'actual','value_column':'target','operator':'>','group_by':['region'],'sort_by':'percentage'}
        r=self.publish('comparison_summary',p,pd.DataFrame({'region':['a','b'],'actual':[float('nan'),float('nan')],'target':[1.,2.]}))
        self.assertEqual(r['analysis_package']['charts'],[])
        self.assertIn('undefined',r['content']);self.assertEqual([row['Matched Percentage'] for row in r['results']['data']],[None,None])
    def test_sorting_is_checked_on_rows_not_only_evidence_labels(self):
        p={'column':'actual','value_column':'target','operator':'>','group_by':['region'],'sort_by':'percentage'}
        r=execute('comparison_summary',p,pd.DataFrame({'region':['a','b'],'actual':[0,1],'target':[0,0]}))
        r['data'].reverse();stamp('comparison_summary',p,r)
        table={'id':'x','tool':'comparison_summary','parameters':p,'result':r,'source':{'tables':['fixture'],'join_keys':[]}}
        checks=publication_checks({'outputs':[{'id':'requested','kind':'comparison_summary','parameters':p}]},[table])
        self.assertEqual(checks[0]['status'],'missing')
    def test_table_presentation_is_an_explicit_specification_field(self):
        from app.services.answer_summary import render
        table={'id':'x','label':'Value','parameters':{},'result':{'columns':['value'],'data':[{'value':7}]}}
        self.assertNotIn('|',render([table],'Show a table in chat.'))
        self.assertIn('| value |',render([table],'Calculate',table_in_chat=True))
    def test_repair_cannot_shrink_independent_request_requirements(self):
        p={'group_by':['region'],'aggregations':{'value':'sum'}}
        plan={'intent':'SIMPLE','analysis_plan':{'source':{'tables':['fixture']},'outputs':[{'id':'sum','kind':'aggregation','parameters':p}]},
              'request_requirements':{'outputs':[{'id':'needed','kind':'aggregation','parameters':p,'sort_by':'value','ascending':False}]}}
        other=copy.deepcopy(plan);other['request_requirements']['outputs'][0].pop('sort_by')
        with self.assertRaises(ContractError):guard_repair(plan,other)
