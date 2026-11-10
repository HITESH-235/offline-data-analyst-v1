"""Schema/consumer agreement for nullable constraints, including the live failure."""
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.analysis.operations import OutputRequirement, MeasureRequirement, CompletionContract, validate_contract, validate_plan, execute, guard_repair, ContractError, canonical_planner_requirements
from app.api.v1.chat import process_chat_message
from app.api.v1.projects import list_saved_analyses
from app.models.chat import ChatRequest
from app.models.project import DBProject
from app.services.analysis_package import validate_requirements, OutputAccumulator, finalize
from app.storage.sqlite.session import Base

CAPTURE=json.loads((Path(__file__).parent/'fixtures/nullable_requirement_observation.json').read_text())
QUESTION=('Among delivered orders, compare the calendar date of order_delivered_customer_date with order_estimated_delivery_date. '
          'Same-day delivery is on time. Join customers on customer_id and return every customer_state with comparable orders, late orders, and late percentage. '
          'Exclude missing dates from each percentage denominator and report missing dates separately. Sort by late percentage descending.')

class NullableContractTest(unittest.TestCase):
    def test_each_nullable_output_field_and_all_null_fields_equal_omission(self):
        properties=OutputRequirement.model_json_schema()['properties']
        fields=[name for name,field in OutputRequirement.model_fields.items()
                if not field.is_required() and any(branch.get('type')=='null' for branch in properties[name].get('anyOf',[]))]
        base={'outputs':[{'id':'comparison','kind':'comparison_summary'}]}
        expected=validate_requirements(base)
        for name in fields:
            with self.subTest(field=name):
                value=copy.deepcopy(base);value['outputs'][0][name]=None
                self.assertEqual(validate_requirements(value),expected)
        value=copy.deepcopy(base);value['outputs'][0].update(dict.fromkeys(fields));value['chart_scope']=None
        self.assertEqual(validate_requirements(value),expected)
        self.assertEqual(value['outputs'][0]['columns'],None)  # caller input is unchanged
    def test_nested_nullable_measure_fields_do_not_reject_valid_requirements(self):
        measure={'source_column':'value','operation':'sum'}
        for name,field in MeasureRequirement.model_fields.items():
            if field.default is None and name not in measure:measure[name]=None
        contract={'outputs':[{'id':'sum','kind':'aggregation','group_by':[], 'measures':[measure],
                             'scope':{'mode':'all','limit':None},'ascending':False}],
                  'chart_scope':{'required':False,'top_n':10}}
        normalized=validate_requirements(contract)
        self.assertEqual(normalized['outputs'][0]['measures'],[{'source_column':'value','operation':'sum'}])
        self.assertEqual(normalized['outputs'][0]['group_by'],[])
        self.assertEqual(normalized['outputs'][0]['scope'],{'mode':'all'})
        self.assertIs(normalized['outputs'][0]['ascending'],False)
        self.assertIs(normalized['chart_scope']['required'],False)
    def test_literal_null_predicates_and_opaque_data_are_preserved(self):
        predicate={'column':'status','operator':'==','value':None,'value_column':None,'value_type':None,'date_part':None}
        p={'column':'actual','value_column':'target','operator':'>','group_by':['region'],'sort_by':'percentage',
           'eligibility_filters':[predicate]}
        contract={'outputs':[{'id':'c','kind':'comparison_summary','parameters':p,'filters':[predicate],
                              'measures':None,'columns':None,'scope':None}],'chart_scope':None}
        normalized=validate_requirements(contract)
        expected=[{'column':'status','operator':'==','value':None}]
        self.assertEqual(normalized['outputs'][0]['filters'],expected)
        self.assertEqual(normalized['outputs'][0]['parameters']['eligibility_filters'],expected)
        frame=pd.DataFrame({'region':['a','a','a'],'status':[None,'ok',None],
                            'actual':[5.,2.,0.],'target':[3.,3.,float('nan')]})
        result=execute('comparison_summary',p,frame)
        self.assertEqual(result['comparison_audit']['filtered_count'],2)
        self.assertEqual(result['comparison_audit']['comparable_count'],1)
        accumulator=OutputAccumulator();accumulator.record('comparison_summary',p,result,{'tables':['fixture']},0,'c',normalized)
        published=finalize({'analysis_outputs':accumulator.export()},'Compare values.','test','reply',normalized)
        self.assertEqual(published['analysis_status'],'complete')
        opaque={'outputs':[{'id':'f','kind':'filtering','filters':[{'column':'x','operator':'==','value':{'nested':None}}]}]}
        self.assertEqual(validate_contract(opaque)['outputs'][0]['filters'][0]['value'],{'nested':None})
    def test_semantic_sorts_resolve_for_grouped_and_scalar_comparison_labels(self):
        frame=pd.DataFrame({'zone':['a','b','b'],'actual':[4,0,1],'target':[2,1,0]})
        for groups in ([],['zone']):
            for key in ('percentage','matched_count','comparable_count'):
                with self.subTest(groups=groups,sort=key):
                    p={'column':'actual','operator':'>','value_column':'target','group_by':groups,
                       'matched_label':'Above','count_label':'Cases','sort_by':key,'ascending':False}
                    contract=validate_requirements({'outputs':[{'id':'c','kind':'comparison_summary','parameters':p,
                               'columns':None,'measures':None,'sort_by':key,'ascending':False}]})
                    result=execute('comparison_summary',p,frame)
                    accumulator=OutputAccumulator();accumulator.record('comparison_summary',p,result,{'tables':['fixture']},0,'c',contract)
                    final=finalize({'analysis_outputs':accumulator.export()},'Compare values.','test','reply',contract)
                    self.assertEqual(final['analysis_status'],'complete',final['content'])

    def test_explicit_lists_false_and_zero_keep_their_meaning(self):
        contract={'outputs':[{'id':'sum','kind':'aggregation','parameters':{'group_by':[], 'aggregations':{'x':'sum'},
                              'filters':[{'column':'x','operator':'>=','value':0}]},
                             'columns':[],'group_by':[],'filters':[],'measures':[],'source_tables':[],
                             'join_keys':[],'ascending':False}]}
        out=validate_requirements(contract)['outputs'][0]
        for key in ('columns','group_by','filters','measures','source_tables','join_keys'):self.assertEqual(out[key],[])
        self.assertIs(out['ascending'],False)
        self.assertEqual(out['parameters']['filters'][0]['value'],0)
    def test_invalid_required_nulls_unknown_fields_and_wrong_types_still_fail(self):
        base={'outputs':[{'id':'c','kind':'comparison_summary'}]}
        invalid=[{'outputs':None},{'outputs':[]},{'outputs':[{'id':None,'kind':'comparison_summary'}]},
                 {'outputs':[{'id':'c','kind':None}]}, {'outputs':[{'id':'c','kind':'comparison_summary','unknown':None}]},
                 {**base,'unknown':None}, {**base,'chart_scope':{'top_n':None}},
                 {'outputs':[{'id':'a','kind':'aggregation','parameters':None,'group_by':None,'measures':None}]}]
        for key,value in [('columns','x'),('group_by',{}),('filters',False),('measures','x'),('ascending',0),
                          ('source_tables',['x',None]),('scope',{'mode':'top','limit':None})]:
            invalid.append({'outputs':[{'id':'c','kind':'comparison_summary',key:value}]})
        for value in invalid:
            with self.subTest(value=value),self.assertRaises(ValueError):validate_requirements(value)
        p=copy.deepcopy(CAPTURE['attempts'][0]['output']);p['analysis_plan']['outputs'][0]['parameters']['eligibility_filters']=None
        with self.assertRaises(ValueError):validate_plan(p)
    def test_typed_full_dump_round_trip_and_repair_treat_null_as_unset(self):
        minimal={'outputs':[{'id':'c','kind':'comparison_summary','parameters':{'column':'x','operator':'>','value_column':'y'}}]}
        expanded=CompletionContract.model_validate(minimal).model_dump()
        self.assertEqual(validate_requirements(json.loads(json.dumps(expanded))),validate_requirements(minimal))
        plan=copy.deepcopy(CAPTURE['attempts'][0]['output'])
        omitted=validate_plan(plan)
        guard_repair(plan,omitted)
        changed=copy.deepcopy(omitted);changed['analysis_plan']['outputs'][0]['parameters']['operator']='>='
        with self.assertRaises(ContractError):guard_repair(plan,changed)
    def test_both_captured_attempts_parse_without_erasing_real_column_constraints(self):
        first=validate_plan(CAPTURE['attempts'][0]['output'])
        spec=canonical_planner_requirements(CAPTURE['attempts'][0]['output']['request_requirements'])['outputs'][0]
        self.assertNotIn('columns',spec);self.assertNotIn('measures',spec);self.assertNotIn('scope',spec)
        second=validate_plan(CAPTURE['attempts'][1]['output'])
        self.assertEqual(canonical_planner_requirements(CAPTURE['attempts'][1]['output']['request_requirements'])['outputs'][0]['columns'],
                         ['customer_state','order_delivered_customer_date','order_estimated_delivery_date','order_status'])

class NullableCapturedRouteTest(unittest.TestCase):
    def setUp(self):
        self.engine=create_engine('sqlite://');Base.metadata.create_all(self.engine);self.db=Session(self.engine)
        self.db.add(DBProject(id='test',name='Test'));self.db.commit()
    def tearDown(self):self.db.close();self.engine.dispose()
    def replay(self,output):
        with patch('app.llm.client.OllamaClient.call_model',return_value=json.dumps(output)) as planner,patch('app.llm.agent.OllamaClient.call_model_chat') as interpreter:
            result,failed=process_chat_message(ChatRequest(project_id='test',dataset_id='olist.db::orders',message=QUESTION),self.db,lambda stage:None)
        self.assertEqual(planner.call_count,1);interpreter.assert_not_called()
        return result,failed
    def test_original_first_attempt_completes_without_schema_repair(self):
        result,failed=self.replay(CAPTURE['attempts'][0]['output'])
        self.assertFalse(failed,result['content']);self.assertEqual(result['analysis_status'],'complete')
        self.assertEqual(result['results']['row_count'],27)
        self.assertEqual([r['customer_state'] for r in result['results']['data'][:3]],['AL','MA','SE'])
        self.assertIn('6.773090%',result['content']);self.assertIn('**AL:** 21.410579%',result['content'])
        self.assertEqual(result['analysis_package']['charts'][0]['specification']['y'],'Late Percentage')
        self.assertEqual(len(result['planner_diagnostics']),1);self.assertTrue(result['planner_diagnostics'][0]['accepted'])
        saved=list_saved_analyses('test',self.db)[0];self.assertEqual(saved['analysisPackage'],result['analysis_package'])
    def test_redundant_source_column_preview_does_not_replace_native_outputs(self):
        result,failed=self.replay(CAPTURE['attempts'][1]['output'])
        self.assertFalse(failed,result['content']);self.assertEqual(result['analysis_status'],'complete')
        self.assertEqual(result['results']['row_count'],27)
        self.assertEqual(result['results']['columns'],['customer_state','Comparable Orders','Late Orders','Late Percentage','Missing Actual Date','Missing Estimated Date'])
