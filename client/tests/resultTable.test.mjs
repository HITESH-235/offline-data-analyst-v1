import test from 'node:test';
import assert from 'node:assert/strict';
import {sortResultRows, displayValue} from '../src/components/chat/tableValues.js';
import {inspectResult, rankRows, makeChart} from '../src/components/dataset/charts/chartModel.js';

test('null percentage values sort last in both directions without altering saved rows', () => {
  const rows=[{p:null},{p:0},{p:21.4},{p:6.7}];
  assert.deepEqual(sortResultRows(rows,{column:'p',direction:1}).map(r=>r.p),[0,6.7,21.4,null]);
  assert.deepEqual(sortResultRows(rows,{column:'p',direction:-1}).map(r=>r.p),[21.4,6.7,0,null]);
  assert.equal(rows[0].p,null); assert.equal(displayValue(null),'Undefined');
});

test('grouped percentage chart reads the same verified table and Top N changes only the chart', () => {
  const result={analysis_kind:'comparison_summary',columns:['state','Comparable Orders','Late Orders','Late Percentage'],
    data:Array.from({length:27},(_,i)=>({state:'S'+i,'Comparable Orders':100,'Late Orders':i,'Late Percentage':i})),units:{'Late Percentage':'%'}};
  const original=structuredClone(result);
  const model=inspectResult(result,null,'Break down late rates');
  assert.ok(model.choices.bar.some(p=>p.x==='state'&&p.y==='Late Percentage'));
  const ranking=rankRows(result.data,'state','Late Percentage');
  const chart=makeChart(model,'bar','state','Late Percentage',ranking,10);
  assert.equal(chart.rows.length,10);assert.equal(chart.rows[0].value,26);
  assert.equal(result.data.length,27);assert.deepEqual(result,original);
});

test('percentage bar labels are readable while chart values retain full precision', () => {
  const result={analysis_kind:'comparison_summary',columns:['state','Late Percentage'],
    data:[{state:'AL','Late Percentage':21.410579345088163},{state:'MA','Late Percentage':17.433751743375176}],units:{'Late Percentage':'%'}};
  const model=inspectResult(result,null,'Late rates');
  const chart=makeChart(model,'bar','state','Late Percentage',rankRows(result.data,'state','Late Percentage'),10);
  assert.deepEqual(chart.traces[0].text,['21.41%','17.43%']);
  assert.equal(chart.traces[0].x[0],21.410579345088163);
  assert.match(chart.traces[0].hovertemplate,/\.6f/);
  assert.match(chart.details[0],/21\.410579%/);
});
