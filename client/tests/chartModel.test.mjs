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
