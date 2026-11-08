import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { inspectResult, rankRows, makeChart, dateValue } from '../src/components/dataset/charts/chartModel.js';
import { fixtures } from './fixtures/charts.mjs';
const inspect = snapshot => inspectResult(snapshot.result,snapshot.calculation,snapshot.question);
const render = (snapshot,type) => { const model=inspect(snapshot);const {x,y}=model.choices[type][0];return makeChart(model,type,x,y,rankRows(model.data,x,y)); };
for (const [fixture,type] of Object.entries({ranking:'bar',monthly:'line',scatter:'scatter',distribution:'histogram',grouped:'box',correlation:'heatmap'})) {
 test(`${fixture} selects ${type}`,()=>assert.equal(inspect(fixtures[fixture]).preferred,type));
}
test('Northwind top 5 and 10 match full saved values regardless of row order',()=>{
 const snapshot=JSON.parse(readFileSync(new URL('./fixtures/northwind-ranking.json',import.meta.url)));
 const expected=[...snapshot.result.data].sort((a,b)=>b.Quantity-a.Quantity);
 const ranking=rankRows([...snapshot.result.data].reverse(),'ProductName','Quantity');
 for(const n of [5,10,20])assert.deepEqual(ranking.slice(0,n).map(row=>[row.label,row.value]),expected.slice(0,n).map(row=>[row.ProductName,row.Quantity]));
 assert.equal(expected[0].Quantity,206213);
});
test('large fixture retains only the best 20 without mutating input',()=>{
 const rows=Array.from({length:50000},(_,i)=>({Name:`Item ${i}`,Value:i-25000}));
 const ranking=rankRows(rows,'Name','Value');assert.equal(ranking.length,20);assert.equal(ranking[0].value,24999);assert.equal(rows[0].Value,-25000);
});
test('bar retains negatives, zero, full labels and counts nulls',()=>{
 const chart=render(fixtures.ranking,'bar');assert.deepEqual(chart.traces[0].x,[20,0,-10]);assert.equal(chart.omitted,1);assert.ok(chart.details[0].includes('more than one line'));
});
test('line uses chronological dates and ignores Top N',()=>{
 const chart=render(fixtures.monthly,'line');assert.deepEqual(chart.traces[0].x,['2025-01-01T00:00:00.000Z','2025-02-01T00:00:00.000Z','2025-12-01T00:00:00.000Z']);assert.equal(chart.omitted,1);
});
test('invalid and ambiguous dates are not parsed',()=>{for(const value of ['2025-02-30','01/02/2025','2025-13','2025-01-01T25:00Z'])assert.equal(dateValue(value),null);});
test('duplicate categories and dates cannot silently aggregate',()=>{
 const snapshot={result:{columns:['Name','Date','Value'],data:[{Name:'A',Date:'2025-01',Value:2},{Name:'A',Date:'2025-01',Value:4}]}};
 const model=inspect(snapshot);assert.equal(model.choices.bar.length,0);assert.equal(model.choices.line.length,0);assert.equal(model.preferred,'');
});
test('aggregates never offer distributions even with raw override',()=>{
 const s=fixtures.ranking;const model=inspectResult(s.result,s.calculation,s.question,'raw');assert.equal(model.choices.histogram.length,0);assert.equal(model.choices.box.length,0);
});
test('numeric IDs are excluded from measures',()=>{assert.deepEqual(inspect(fixtures.scatter).numbers,['Height','Weight']);});
test('ambiguous measures require field selection',()=>{assert.deepEqual(inspect(fixtures.ambiguous).initial,{x:'',y:''});});
test('empty or all-null results have no chart',()=>{assert.equal(inspect(fixtures.empty).types.length,0);assert.equal(inspectResult({columns:['X'],data:[{X:null}]}).types.length,0);});
test('histogram counts every finite raw observation including maximum',()=>{const chart=render(fixtures.distribution,'histogram');assert.equal(chart.traces[0].y.reduce((a,b)=>a+b,0),9);assert.equal(chart.omitted,1);});
test('constant histogram has one bin',()=>{const s={result:{columns:['Value'],data:[{Value:2},{Value:2}]},calculation:fixtures.distribution.calculation};const chart=render(s,'histogram');assert.deepEqual(chart.traces[0].y,[2]);});
test('box uses quartiles and preserves outliers',()=>{const chart=render(fixtures.grouped,'box');assert.equal(chart.traces[0].median[0],2);assert.deepEqual(chart.traces[1].y,[100]);assert.equal(chart.omitted,1);});
test('heatmap displays supplied matrix rather than recomputing it',()=>{const chart=render(fixtures.correlation,'heatmap');assert.deepEqual(chart.traces[0].z,[[1,-.75],[-.75,1]]);});
test('malformed matrix cannot be offered',()=>{const s=structuredClone(fixtures.correlation);s.result.correlation.matrix=[[1,3]];assert.equal(inspect(s).choices.heatmap.length,0);});
test('unknown observations require confirmation before distributions',()=>{const result={columns:['Value'],data:[{Value:1},{Value:2}]};assert.equal(inspectResult(result).types.length,0);assert.equal(inspectResult(result,null,'','raw').preferred,'histogram');});
test('declared categorical codes are not numeric measures',()=>{
 const model=inspectResult({columns:['Region','Value'],data:[{Region:1,Value:2},{Region:2,Value:4}],data_types:{Region:'category'}});
 assert.deepEqual(model.categories,['Region']);assert.deepEqual(model.numbers,['Value']);
});
test('declared timestamps with unknown epoch units are not guessed',()=>{
 const model=inspectResult({columns:['Time','Value'],data:[{Time:1700000000,Value:2},{Time:1700000001,Value:4}],data_types:{Time:'timestamp'}});
 assert.deepEqual(model.dates,[]);assert.deepEqual(model.numbers,['Value']);
});
test('small-sample box whiskers never fall inside the quartile box',()=>{
 const chart=render(fixtures.grouped,'box');
 chart.traces[0].q1.forEach((q1,i)=>{assert.ok(chart.traces[0].lowerfence[i]<=q1);assert.ok(chart.traces[0].upperfence[i]>=chart.traces[0].q3[i]);});
});
test('verified monthly revenue opens as chronological line and cannot become a distribution',()=>{
 const snapshot={result:{columns:['Month','Revenue'],data:[{Month:'2022-02',Revenue:20},{Month:'2022-01',Revenue:10}],data_types:{Month:'date',Revenue:'float'},analysis_kind:'monthly_revenue'},calculation:{steps:[{tool:'monthly_revenue',status:'succeeded'}]}};
 const model=inspectResult(snapshot.result,snapshot.calculation,'show monthly revenue for year 2022','raw');
 assert.equal(model.preferred,'line');assert.equal(model.choices.histogram.length,0);assert.equal(model.choices.box.length,0);
 const chart=makeChart(model,'line','Month','Revenue',[],10);
 assert.deepEqual(chart.traces[0].y,[10,20]);
});
test('validated correlation table and heatmap share all coefficients and requested order',()=>{
 const columns=['Discount','UnitPrice','Quantity'];
 const matrix=[[1,-.0030953092568265475,.004464951441794699],[-.0030953092568265475,1,.0006114333954079673],[.004464951441794699,.0006114333954079673,1]];
 const result={analysis_kind:'correlation',source_observation_count:609283,row_count:3,columns:['Measure',...columns],correlation:{columns,matrix},data:columns.map((Measure,i)=>Object.fromEntries([['Measure',Measure],...columns.map((c,j)=>[c,matrix[i][j]])]))};
 const model=inspectResult(result);assert.deepEqual(model.types,['heatmap']);
 const chart=makeChart(model,'heatmap','','',[],10);
 assert.deepEqual(chart.traces[0].x,columns);assert.deepEqual(chart.traces[0].y,columns);
 assert.deepEqual(chart.traces[0].z,result.data.map(row=>columns.map(c=>row[c])));
 assert.deepEqual(chart.traces[0].text,matrix.map(row=>row.map(v=>v.toFixed(4))));
 assert.equal(chart.traces[0].texttemplate,'%{text}');
});
test('explicit identifier correlation measures are preserved and undefined coefficients remain null',()=>{
 const result={analysis_kind:'correlation',correlation:{columns:['OrderID','Quantity'],matrix:[[1,null],[null,null]]},columns:['Measure','OrderID','Quantity'],data:[{Measure:'OrderID',OrderID:1,Quantity:null},{Measure:'Quantity',OrderID:null,Quantity:null}]};
 const model=inspectResult(result);assert.deepEqual(model.matrix.columns,['OrderID','Quantity']);
 const chart=makeChart(model,'heatmap','','',[],10);
 assert.deepEqual(chart.traces[0].z,[[1,null],[null,null]]);assert.equal(chart.traces[0].text[0][1],'N/A');
});
test('captured Northwind table, heatmap labels and grounded narrative agree',()=>{
 const saved=JSON.parse(readFileSync(new URL('./fixtures/northwind-correlation.json',import.meta.url)));
 const result=saved.result, model=inspectResult(result);
 const chart=makeChart(model,'heatmap','','',[],10);
 assert.equal(result.source_observation_count,609283);
 assert.equal(result.row_count,3);
 assert.deepEqual(chart.traces[0].x,['UnitPrice','Quantity','Discount']);
 assert.deepEqual(chart.traces[0].y,chart.traces[0].x);
 assert.deepEqual(chart.traces[0].z,result.data.map(row=>chart.traces[0].x.map(c=>row[c])));
 chart.traces[0].text.flat().forEach(label=>assert.ok(saved.content.includes(label)));
 assert.ok(saved.content.includes('609,283'));
 assert.ok(saved.content.includes('do not establish statistical independence'));
});
test('correlation heatmap fixes diverging scale at minus one, zero and plus one',()=>{
 const captured=JSON.parse(readFileSync(new URL('./fixtures/northwind-correlation.json',import.meta.url)));
 const model=inspectResult(captured.result);
 const chart=makeChart(model,'heatmap','','',[],10), trace=chart.traces[0];
 assert.equal(trace.zmin,-1);assert.equal(trace.zmax,1);assert.equal(trace.zmid,0);assert.equal(trace.zauto,false);
 assert.equal(trace.colorscale[1][0],.5);
 assert.notEqual(trace.colorscale[0][1],trace.colorscale[2][1]);
 assert.equal(trace.texttemplate,'%{text}');assert.deepEqual(trace.x,trace.y);
});
test('calendar comparison plots all aligned quarterly series from the result table without Top N',()=>{
 const data=[1,2,3,4].map(q=>({Quarter:`Q${q}`,'Revenue 2021':q*10,'Revenue 2022':q*20}));
 const result={analysis_kind:'calendar_aggregate',columns:['Quarter','Revenue 2021','Revenue 2022'],data,
   analysis_context:{metric:{name:'Revenue'}},calendar_chart:{x:'Quarter',series:['Revenue 2021','Revenue 2022'],grain:'quarter'}};
 const model=inspectResult(result);assert.equal(model.preferred,'line');assert.deepEqual(model.initial,{x:'Quarter',y:'Revenue'});
 const chart=makeChart(model,'line','Quarter','Revenue',[],1);
 assert.deepEqual(chart.traces[0].x,['Q1','Q2','Q3','Q4']);assert.deepEqual(chart.traces[1].x,chart.traces[0].x);
 for(const trace of chart.traces)assert.deepEqual(trace.y,data.map(row=>row[trace.name]));
 assert.equal(chart.calendar,true);assert.equal(chart.details.length,8);assert.equal(model.raw,false);
});
test('restored monthly comparison preserves twelve periods and both year series',()=>{
 const data=Array.from({length:12},(_,i)=>({Month:String(i+1).padStart(2,'0'),'Revenue 2021':100+i,'Revenue 2022':200+i}));
 const result={analysis_kind:'calendar_aggregate',columns:['Month','Revenue 2021','Revenue 2022'],data,
   analysis_context:{metric:{name:'Revenue'},years:[2021,2022],compare:true,grain:'month'},
   calendar_chart:{x:'Month',series:['Revenue 2021','Revenue 2022'],grain:'month'}};
 const model=inspectResult(result);const chart=makeChart(model,'line','Month','Revenue',[],5);
 assert.equal(chart.traces.length,2);
 for(const trace of chart.traces){assert.equal(trace.x.length,12);assert.deepEqual(trace.y,data.map(row=>row[trace.name]));}
 assert.deepEqual(chart.traces[0].x,data.map(row=>row.Month));
 assert.deepEqual(chart.traces[0].x,chart.traces[1].x);
});
test('aggregation count provenance makes identifiers usable measures while raw identifiers stay excluded',()=>{
 const result={columns:['order_status','order_id'],data:[{order_status:'delivered',order_id:96478},{order_status:'canceled',order_id:625}],measure_provenance:{order_id:{source_column:'order_id',operation:'count',role:'measure'}}};
 assert.deepEqual(inspectResult(result).numbers,['order_id']);
 assert.deepEqual(inspectResult({...result,measure_provenance:{}}).numbers,[]);
 const legacy=inspectResult({...result,measure_provenance:{}},{steps:[{tool:'aggregation',status:'succeeded',parameters:{aggregations:{order_id:'count'}}}]});
 assert.deepEqual(legacy.numbers,['order_id']);
});
test('BRL chart bars, labels and hover use transformed saved values without dividing again',()=>{
 const result={analysis_kind:'aggregation',columns:['payment_type','Payments (BRL)'],data:[{payment_type:'credit_card','Payments (BRL)':12542084.19},{payment_type:'boleto','Payments (BRL)':2869361.27}],units:{'Payments (BRL)':'BRL'},measure_provenance:{'Payments (BRL)':{operation:'sum',source_column:'payment_value_cents',transform:{divide_by:100}}}};
 const model=inspectResult(result);const ranking=rankRows(model.data,'payment_type','Payments (BRL)');
 const chart=makeChart(model,'bar','payment_type','Payments (BRL)',ranking,10);
 assert.deepEqual(chart.traces[0].x,result.data.map(r=>r['Payments (BRL)']));
 assert.ok(chart.details[0].includes('12,542,084.19'));assert.equal(chart.yLabel,'payment_type');
});
