import test from 'node:test';
import assert from 'node:assert/strict';
import {calculationOutputs, calculationSources, chartsForOutput} from '../src/components/dataset/analysisPackage.js';
import {inspectResult, makeChart, rankRows} from '../src/components/dataset/charts/chartModel.js';
const result={analysis_kind:'aggregation',columns:['Region','Order Count'],data:[{Region:'North','Order Count':3},{Region:'South','Order Count':1}],measure_provenance:{'Order Count':{operation:'count',source_column:'order_id'}}};
const pack={status:'complete',tables:[{id:'counts',result,source:{tables:['olist.db::orders']}},{id:'payments',result,source:{tables:['olist.db::order_payments']}}],charts:[{id:'bar',kind:'result',table_id:'counts',specification:{chart_type:'bar'}},{id:'other',kind:'result',table_id:'counts',specification:{chart_type:'scatter'}},{id:'png',kind:'artifact',table_id:'counts'}]};
test('package outputs and sources survive snapshot serialization independently of browsed table',()=>{
 const snapshot=JSON.parse(JSON.stringify({analysisPackage:pack,result:{columns:['raw'],data:[]},datasetId:'olist.db::customers'}));
 assert.deepEqual(calculationOutputs(snapshot),pack.tables);
 assert.deepEqual(calculationSources(snapshot.analysisPackage),['olist.db::orders','olist.db::order_payments']);
 assert.equal(snapshot.datasetId,'olist.db::customers');
 assert.deepEqual(chartsForOutput(pack,'counts').map(c=>c.id),['bar','other']);
});
test('failed package does not fall back to unrelated legacy rows',()=>{
 assert.deepEqual(calculationOutputs({analysisPackage:{status:'failed',tables:[]},result}),[]);
 assert.equal(calculationOutputs({result})[0].result,result);
});
test('charts use calculated measure counts and full result rows',()=>{
 const model=inspectResult(pack.tables[0].result);
 assert.equal(model.preferred,'bar');
 const ranked=rankRows(model.data,'Region','Order Count');
 const chart=makeChart(model,'bar','Region','Order Count',ranked,10);
 assert.deepEqual(chart.traces[0].x,[3,1]);
 assert.deepEqual(result.data,[{Region:'North','Order Count':3},{Region:'South','Order Count':1}]);
});
