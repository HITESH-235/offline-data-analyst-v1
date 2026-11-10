// Exercise the same offline chart model used by Result, without a browser/model call.
import fs from 'node:fs';
import path from 'node:path';
import {inspectResult, makeChart, rankRows} from '../../client/src/components/dataset/charts/chartModel.js';
const folder=process.argv[2];
const records=[];
for(const name of fs.readdirSync(folder).filter(name=>/^[QH]\d\d\.json$/.test(name)).sort()) {
 const record=JSON.parse(fs.readFileSync(path.join(folder,name),'utf8'));
 const snapshot=record.reopened_analysis;
 const pack=snapshot?.analysisPackage;
 const charts=[];
 for(const chartSpec of pack?.charts || []) {
  if(chartSpec.kind!=='result')continue;
  const table=pack.tables.find(t=>t.id===chartSpec.table_id);
  if(!table){charts.push({id:chartSpec.id,error:'Chart references a missing table'});continue;}
  const model=inspectResult(table.result,snapshot.calculation,snapshot.question);
  const spec=chartSpec.specification || {};
  const explicit=model.choices[spec.chart_type]?.find(p=>p.x===spec.x && (p.y===spec.y || !p.y));
  const type=explicit?spec.chart_type:model.preferred;
  const fields=explicit || model.initial;
  const ranking=type==='bar'?rankRows(model.data,fields.x,fields.y):[];
  const plot=makeChart(model,type,fields.x,fields.y,ranking,pack.chart_scope?.top_n || 10);
  let tableAgreement=null;
  if(plot && type==='bar') tableAgreement=JSON.stringify(plot.traces[0].x)===JSON.stringify(ranking.slice(0,pack.chart_scope?.top_n || 10).map(r=>r.value));
  else if(plot && type==='line' && table.result.calendar_chart) tableAgreement=plot.traces.every(t=>JSON.stringify(t.y)===JSON.stringify(table.result.data.map(row=>row[t.name])));
  else if(plot && type==='scatter') tableAgreement=JSON.stringify(plot.traces[0].x)===JSON.stringify(table.result.data.map(row=>row[fields.x])) && JSON.stringify(plot.traces[0].y)===JSON.stringify(table.result.data.map(row=>row[fields.y]));
  charts.push({table_values_agree:tableAgreement,id:chartSpec.id,table_id:table.id,type,fields,requested_type:spec.chart_type,specification_compatible:!spec.chart_type || Boolean(explicit),plot_available:Boolean(plot),table_rows:table.result.data.length,traces:plot?.traces,details:plot?.details,omitted:plot?.omitted});
 }
 records.push({id:name.slice(0,3),charts});
}
fs.writeFileSync(path.join(folder,'chart-assessment.json'),JSON.stringify(records,null,2));
for(const r of records)console.log(r.id,JSON.stringify(r.charts.map(c=>({type:c.type,plot_available:c.plot_available,table_rows:c.table_rows,trace_lengths:c.traces?.map(t=>({x:t.x?.length,y:t.y?.length}))}))));
