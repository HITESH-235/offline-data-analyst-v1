import test from 'node:test';
import assert from 'node:assert/strict';
import { chatPresentation, chatContent } from '../src/components/chat/resultPresentation.js';
import { calculationDetailSteps } from '../src/components/chat/calculationMetadata.js';

const table = (id, value, parameters = {}) => ({ id, tool: 'aggregation', parameters, result: { analysis_kind: 'aggregation', columns: [id], data: [{ [id]: value }] } });
test('scalar and three-count packages stay in chat after historical reload without discarding results', () => {
  const pack = { tables: [table('Total',99441),table('With',99440),table('Without',1)], charts: [] };
  const before = structuredClone(pack);
  assert.equal(chatPresentation(pack).hasDetail,false);
  assert.equal(chatPresentation(JSON.parse(JSON.stringify(pack))).hasDetail,false);
  assert.equal(chatContent('Counts. The full breakdown is available in **Open result**.',false),'Counts.');
  assert.deepEqual(pack,before);
  assert.equal(chatPresentation({tables:[table('Total',99441)]}).hasDetail,false);
});
test('semantic detail and explicit table or chart decisions survive reload', () => {
  assert.equal(chatPresentation({tables:[table('Sales',7,{group_by:['region']})]}).hasDetail,true);
  assert.equal(chatPresentation({tables:[{result:{analysis_kind:'calendar_aggregate',columns:['Month','Sales'],data:[{Month:'2021-01',Sales:7}]}}]}).hasDetail,true);
  assert.equal(chatPresentation({tables:[table('Total',7)],presentation:{has_detail:true,table_requested:true}}).hasDetail,true);
  assert.equal(chatPresentation({tables:[table('Total',7)],charts:[{kind:'result',id:'c'}],chart_scope:{required:true}}).hasDetail,true);
});
test('sources, filters, formulas and disjoint exclusions come from saved metadata after reload', () => {
  const pack={tables:[{id:'review',result:{entity_audit:{missing_actual_count:6,missing_comparison_count:0,missing_record_count:315,unusable_measurement_count:0,exclusion_definition:'Review exclusions apply only to comparable orders.'}}}],provenance:{steps:[{output_id:'review',tool:'entity_comparison',status:'succeeded',tables:['orders','reviews'],parameters:{entity_key:'order_id',filters:[{column:'status',operator:'==',value:'delivered'}],measurement:{name:'Score',expression:{column:'review_score'}}}}]}};
  const details=calculationDetailSteps(null,JSON.parse(JSON.stringify(pack)));
  assert.deepEqual(details[0].sources,['orders','reviews']);assert.match(details[0].filters[0],/delivered/);
  assert.match(details[0].formulas[0],/within order_id.*equal entity weight/);
  assert.match(details[0].exclusions.join(' '),/Missing actual values: 6/);
  assert.match(details[0].exclusions.join(' '),/315 have no measurement records/);
  const p={provenance:{steps:[{tool:'aggregation',status:'succeeded',parameters:{measures:[{id:'paid',column:'cents',operation:'sum',label:'BRL',divide_by:100,unit:'BRL'}]}}]}};
  assert.match(calculationDetailSteps(null,p)[0].formulas[0],/sum\(cents\) \/ 100 \[BRL\]/);
});

test('older table metadata supplies calculation details when provenance steps are absent', () => {
  const pack={tables:[{...table('Total',3),source:{tables:['orders']},parameters:{measures:[{id:'orders',column:'order_id',operation:'count',label:'Total'}]}}]};
  const steps=calculationDetailSteps(null,JSON.parse(JSON.stringify(pack)));
  assert.deepEqual(steps[0].sources,['orders']);assert.match(steps[0].formulas[0],/count\(order_id\)/);
});

test('disabled chart preference survives reload without hiding statistical tables or calculation details', async () => {
  const {chartControlsAvailable,chartsForOutput}=await import('../src/components/dataset/analysisPackage.js');
  const pack=JSON.parse(JSON.stringify({chart_scope:{preference:'disabled'},tables:[{id:'stats',tool:'statistics',parameters:{columns:['reading'],statistics:['count','mean'],unit:'cents'},result:{analysis_kind:'statistics',columns:['column','count','mean'],data:[{column:'reading',count:2,mean:10}]}}],charts:[{id:'old',kind:'result',table_id:'stats'}]}));
  assert.equal(chartControlsAvailable(pack),false);assert.deepEqual(chartsForOutput(pack,'stats'),[]);
  assert.equal(pack.tables.length,1);assert.equal(chatPresentation(pack).hasDetail,true);
  assert.match(calculationDetailSteps(null,pack)[0].formulas[0],/count, mean.*cents.*nonmissing/);
  for(const preference of ['required','automatic'])assert.equal(chartControlsAvailable({chart_scope:{preference}}),true);
  assert.equal(chartControlsAvailable({chart_scope:{required:true}}),true);
});
