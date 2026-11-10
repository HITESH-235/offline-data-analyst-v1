import test from 'node:test';
import assert from 'node:assert/strict';
import { applyPlotTheme } from '../src/theme/chartTheme.js';
import { prepareGeneratedFigure } from '../src/components/dataset/charts/generatedFigure.js';
import { inspectResult, makeChart, rankRows } from '../src/components/dataset/charts/chartModel.js';
import { fixtures } from './fixtures/charts.mjs';
import { palette, contrast } from './fixtures/themeTokens.mjs';

test('all table chart fixtures retain values and fields in both themes',()=>{
  for(const [key,type] of Object.entries({ranking:'bar',monthly:'line',scatter:'scatter',distribution:'histogram',grouped:'box',correlation:'heatmap'})) {
    const f=fixtures[key],model=inspectResult(f.result,f.calculation,f.question),{x,y}=model.choices[type][0];
    const chart=makeChart(model,type,x,y,rankRows(model.data,x,y));const before=structuredClone(chart);
    for(const mode of ['light','dark']) {
      const themed=applyPlotTheme({data:chart.traces,layout:{xaxis:{range:[-2,10]},yaxis:{type:'log'},uirevision:'same-result'}},palette(mode),{managed:true});
      chart.traces.forEach((trace,i)=>{for(const field of ['x','y','z','q1','median','q3','text','hovertemplate','customdata'])assert.deepEqual(themed.data[i][field],trace[field]);});
      assert.equal(themed.layout.paper_bgcolor,palette(mode).surface);assert.deepEqual(themed.layout.xaxis.range,[-2,10]);assert.equal(themed.layout.yaxis.type,'log');assert.equal(themed.layout.uirevision,'same-result');
    }
    assert.deepEqual(chart,before);
  }
});
test('generated figures preserve requested series styles, zoom, annotations, frames and data',()=>{
  const figure={data:[{type:'scatter',x:[1,2],y:[-20,30],line:{color:'red',dash:'dot'},visible:'legendonly'}],layout:{yaxis:{range:[-50,50]},annotations:[{text:'Keep annotation',x:1,y:-20}],uirevision:'custom-view'},frames:[{name:'first'}]};
  const original=structuredClone(figure);const prepared=prepareGeneratedFigure(figure,450);
  for(const mode of ['light','dark']) {
    const r=applyPlotTheme(prepared,palette(mode),{revision:'artifact-id'});
    assert.equal(r.data[0].line.color,'red');assert.equal(r.data[0].line.dash,'dot');assert.equal(r.data[0].visible,'legendonly');
    assert.deepEqual(r.data[0].y,[-20,30]);assert.deepEqual(r.layout.yaxis.range,[-50,50]);assert.equal(r.layout.annotations[0].text,'Keep annotation');assert.equal(r.layout.uirevision,'custom-view');assert.deepEqual(r.frames,figure.frames);
  }
  assert.deepEqual(figure,original);
});
test('correlation stays diverging, centered and fixed, without changing coefficients',()=>{
  const f={data:[{type:'heatmap',z:[[1,-.5],[-.5,1]],text:[['1','-.5'],['-.5','1']],zmin:0,zmax:1}],layout:{title:{text:'Correlation'}}};
  for(const mode of ['light','dark']) {
    const r=applyPlotTheme(f,palette(mode));assert.equal(r.data[0].zmin,-1);assert.equal(r.data[0].zmax,1);assert.equal(r.data[0].zmid,0);assert.equal(r.data[0].zauto,false);assert.deepEqual(r.data[0].z,f.data[0].z);assert.equal(r.data[0].colorscale[1][0],.5);
  }
});
test('theme updates retain revision and distinguish comparison series using markers/dashes',()=>{
  const f={data:[0,1].map(n=>({type:'scatter',mode:'lines+markers',x:[1,2],y:[n,n+1]})),layout:{xaxis:{range:[1.2,1.8]}}};
  const a=applyPlotTheme(f,palette('light'),{managed:true,revision:'result-1'}),b=applyPlotTheme(f,palette('dark'),{managed:true,revision:'result-1'});
  assert.notEqual(a.data[0].line.color,b.data[0].line.color);assert.equal(a.layout.uirevision,b.layout.uirevision);assert.deepEqual(a.layout.xaxis.range,b.layout.xaxis.range);
  assert.notEqual(b.data[0].marker.symbol,b.data[1].marker.symbol);assert.notEqual(b.data[0].line.dash,b.data[1].line.dash);
});
test('generated Plotly Express correlation uses its shared color axis and original title',()=>{
  const f={data:[{type:'heatmap',coloraxis:'coloraxis',z:[[1,.2],[.2,1]],texttemplate:'%{z:.3f}'}],layout:{title:'Correlation heatmap',coloraxis:{cmin:0,cmax:1,colorbar:{title:'Coefficient'}}}};
  const prepared=prepareGeneratedFigure(f,600);
  for(const mode of ['light','dark']) {
    const r=applyPlotTheme(prepared,palette(mode),{sourceLayout:f.layout});
    assert.equal(r.layout.coloraxis.cmin,-1);assert.equal(r.layout.coloraxis.cmax,1);assert.equal(r.layout.coloraxis.cmid,0);assert.equal(r.layout.coloraxis.cauto,false);
    assert.equal(r.layout.coloraxis.colorscale[1][0],.5);assert.equal(r.data[0].texttemplate,'%{z:.3f}');assert.deepEqual(r.data[0].z,f.data[0].z);
  }
});
test('non-correlation numeric color arrays/scales remain data',()=>{
  const f={data:[{type:'scatter',x:[1,2],y:[3,4],marker:{color:[10,20],colorscale:'Viridis',cmin:10,cmax:20}}],layout:{}};
  const r=applyPlotTheme(f,palette('dark'));
  assert.deepEqual(r.data[0].marker.color,[10,20]);assert.equal(r.data[0].marker.colorscale,'Viridis');assert.equal(r.data[0].marker.cmin,10);
});
test('default Plotly palettes migrate, custom colors remain, and donut data survives',()=>{
  const f={data:[{type:'scatter',x:[1],y:[2],line:{color:'#636efa'}},{type:'scatter',x:[1],y:[3],line:{color:'red'}},{type:'pie',labels:['A','B'],values:[20,80],hole:.5}],layout:{}};
  const r=applyPlotTheme(f,palette('dark'));
  assert.equal(r.data[0].line.color,palette('dark').series[0]);assert.equal(r.data[1].line.color,'red');assert.equal(r.data[1].marker.color,'red');
  assert.equal(r.data[2].hole,.5);assert.deepEqual(r.data[2].values,[20,80]);assert.equal(r.data[2].marker.color,undefined);
});
test('values inside bars remain readable against the actual themed fill',()=>{
  for(const mode of ['light','dark']) {
    const r=applyPlotTheme({data:[{type:'bar',x:['A'],y:[42],text:['42'],textposition:'auto'}],layout:{}},palette(mode),{managed:true});
    assert.ok(contrast(r.data[0].insidetextfont.color,r.data[0].marker.color)>=4.5);
  }
});
test('status colors follow labels rather than trace order in both themes',()=>{
  const names=['Failed','Completed','Pending','Running'];
  const f={data:names.map(name=>({type:'scatter',name,mode:'lines+markers',x:[1,2],y:[1,3],line:{color:'#636efa'}})),layout:{}};
  for(const mode of ['light','dark']) {
    const p=palette(mode),r=applyPlotTheme(f,p,{managed:true});
    assert.deepEqual(r.data.map(t=>t.line.color),[p.status.error,p.status.success,p.status.warning,p.status.active]);
    assert.equal(new Set(r.data.map(t=>t.marker.symbol)).size,4);
    const pie=applyPlotTheme({data:[{type:'pie',labels:['Completed','Failed','Pending'],values:[3,2,1],marker:{colors:['#00cc96','#ef553b','#ffa15a']}}],layout:{}},p);
    assert.deepEqual(pie.data[0].marker.colors,[p.status.success,p.status.error,p.status.warning]);
    assert.deepEqual(pie.data[0].values,[3,2,1]);
  }
});
