import test from 'node:test';
import assert from 'node:assert/strict';
import {prepareGeneratedFigure} from '../src/components/dataset/charts/generatedFigure.js';
test('presentation retains values, series, annotations, requested styling and scales',()=>{
 const figure={data:[{type:'scatter',x:[1,2],y:[-10,30],line:{color:'red'}}],layout:{annotations:[{text:'Keep me',x:1,y:-10}],yaxis:{type:'log',range:[1,4]},title:{text:'Title'}},frames:[{name:'one'}]};
 const before=structuredClone(figure),prepared=prepareGeneratedFigure(figure,400);
 assert.deepEqual(figure,before);assert.deepEqual(prepared.data,figure.data);assert.deepEqual(prepared.layout.annotations,figure.layout.annotations);assert.deepEqual(prepared.layout.yaxis.range,[1,4]);assert.equal(prepared.layout.paper_bgcolor,'#FFFFFF');assert.deepEqual(prepared.frames,figure.frames);
});
test('bars retain negative values and a zero baseline without adding Top N',()=>{
 const data=[{type:'bar',x:['A','B'],y:[-2,10]}];const result=prepareGeneratedFigure({data},650);
 assert.equal(result.layout.yaxis.rangemode,'tozero');assert.deepEqual(result.data,data);
});
test('dense categories scroll and disclose the full set rather than drop data',()=>{
 const x=Array.from({length:30},(_,i)=>'Long category '+i),y=x.map((_,i)=>i);
 const result=prepareGeneratedFigure({data:[{type:'bar',x,y}]},350);
 assert.ok(result.scrollWidth>350);assert.match(result.note,/no data is omitted/);assert.equal(result.data[0].x.length,30);
});
test('offline presentation rejects external map and image requirements',()=>{
 assert.throws(()=>prepareGeneratedFigure({data:[{type:'scattergeo'}]},500),/external/);
 assert.throws(()=>prepareGeneratedFigure({data:[{type:'scatter'}],layout:{images:[{source:'https://example.test/image.png'}]}},500),/external/);
});
test('donut charts outside table renderer types are supported without coercion',()=>{
 const data=[{type:'pie',labels:['A','B'],values:[40,60],hole:.5}];assert.deepEqual(prepareGeneratedFigure({data},400).data,data);
});
test('empty figures explain their lack of data',()=>{assert.throws(()=>prepareGeneratedFigure({data:[]},500),/no data/);});
test('empty traces and null-only traces show an explanation instead of blank axes',()=>{
 for(const trace of [{type:'scatter',x:[],y:[]},{type:'scatter',x:[null],y:[null]}]) assert.throws(()=>prepareGeneratedFigure({data:[trace]},500),/no plotted observations/);
});
