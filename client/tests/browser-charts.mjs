// Run separately from builds: node client/tests/browser-charts.mjs
// Uses captured fixtures, intercepts saved-analysis reads, and forbids model requests.
import { spawn } from 'node:child_process';
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises';
import { fixtures } from './fixtures/charts.mjs';
const profile = await mkdtemp('/tmp/chart-browser-');
const port = 19293;
const chrome = spawn(process.env.CHROME_PATH || '/opt/google/chrome/chrome', ['--headless','--no-sandbox','--disable-gpu','--no-proxy-server',`--remote-debugging-port=${port}`,`--user-data-dir=${profile}`,'--window-size=1440,1000','about:blank'], {stdio:'ignore'});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let ws;
try {
 let tabs;
 for(let i=0;i<60;i++){try{tabs=await(await fetch(`http://127.0.0.1:${port}/json`)).json();break;}catch{await sleep(100);}}
 ws=new WebSocket(tabs.find(t=>t.type==='page'&&t.url==='about:blank').webSocketDebuggerUrl);
 await new Promise((r,j)=>{ws.onopen=r;ws.onerror=j;});
 let seq=0;const pending=new Map();const errors=[];
 ws.onmessage=({data})=>{const m=JSON.parse(data);if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails.text);if(pending.has(m.id)){pending.get(m.id)(m.result);pending.delete(m.id);}};
 const call=(method,params={})=>new Promise(r=>{const id=++seq;pending.set(id,r);ws.send(JSON.stringify({id,method,params}));});
 const evaluate=async expression=>{const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);return r.result.value;};
 await call('Runtime.enable');
 await call('Page.navigate',{url:process.env.APP_URL || 'http://127.0.0.1:3001/'});await sleep(1500);
 const northwind=JSON.parse(await readFile(new URL('./fixtures/northwind-ranking.json',import.meta.url),'utf8'));
 const snapshots=[{...northwind,id:'fixture-northwind',content:'Fixture northwind',question:'Fixture northwind: Which products sold the most units?'},...Object.entries(fixtures).map(([name,s])=>({...s,id:`fixture-${name}`,content:`Fixture ${name}`,question:`Fixture ${name}: ${s.question || ''}`})),
 {id:'fixture-large',content:'Fixture large',tables:['Large fixture'],result:{columns:['Label','Score'],data:Array.from({length:50000},(_,i)=>({Label:`Item ${i}`,Score:i-25000}))},calculation:{steps:[{tool:'aggregation',status:'succeeded',parameters:{}}]}}];
 await evaluate(`window.__fixtures=${JSON.stringify(snapshots)};window.__chartRequests=0;window.__modelRequests=0;
 const originalFetch=window.fetch;
 window.fetch=async (...args)=>{const url=String(args[0]);if(url.includes('/api/v1/'))window.__chartRequests++;
 if(url.endsWith('/chat/message/stream'))return new Response(new ReadableStream({start(controller){const send=value=>controller.enqueue(new TextEncoder().encode(JSON.stringify(value)+'\\n'));send({stage:'running_tool'});setTimeout(()=>{const snapshot=window.__fixtures[0];send({stage:'completed',result:{id:'captured-chart-reply',role:'assistant',question:snapshot.question,content:'Captured ranking finished',results:snapshot.result,calculation:snapshot.calculation}});controller.close();},600);}}));
 if(url.includes('/chat/')){window.__modelRequests++;throw Error('Model requests forbidden in chart checks');}
 if(url.endsWith('/analyses'))return Response.json(window.__fixtures);return originalFetch(...args);};`);
 await evaluate(`window.check=(value,label)=>{if(!value)throw Error(label)};
 window.wait=ms=>new Promise(r=>setTimeout(r,ms));
 window.until=async(fn,label)=>{for(let i=0;i<200;i++){if(fn())return fn();await wait(50);}throw Error(label)};
 window.button=(text,root=document)=>[...root.querySelectorAll('button')].find(b=>b.textContent.trim()===text);
 window.openFixture=async name=>{button('Saved Analyses').click();const card=await until(()=>[...document.querySelectorAll('.analysis-entry')].find(b=>b.textContent.includes('Fixture '+name)),'fixture missing '+name);card.click();await wait(60);button('Chart').click();};
 window.graph=()=>document.querySelector('.js-plotly-plot');
 window.ready=async()=>{await until(()=>graph()?._fullLayout&&!document.querySelector('.result-chart [role="alert"]')&&!document.querySelector('.result-chart > p[role="status"]'),'plot not ready');await wait(350);};
 window.choose=async(label,value)=>{const select=[...document.querySelectorAll('.result-chart label')].find(el=>el.firstChild.textContent.trim()===label)?.querySelector('select');check(select,'missing control '+label);select.value=value;select.dispatchEvent(new Event('change',{bubbles:true}));await wait(250);};
 `);
 await evaluate(`(async()=>{(await until(()=>[...document.querySelectorAll('aside .nav-item')].find(b=>b.textContent==='Customers'),'Customers unavailable')).click();await wait(250);})()`);
 const screenshot=async name=>{await evaluate(`(()=>{const body=document.querySelector('.workspace-body');const plot=document.querySelector('.chart-keyboard');if(body&&plot)body.scrollTop+=plot.getBoundingClientRect().top-body.getBoundingClientRect().top-12;})()`);await sleep(60);return writeFile(`/tmp/chart-${name}.png`,Buffer.from((await call('Page.captureScreenshot',{format:'png'})).data,'base64'));};
 console.log(await evaluate(`(async()=>{
 await openFixture('northwind');await ready();const before=__chartRequests;
 check(graph().data[0].x.length===10,'Default Top 10');
 const expected=__fixtures[0].result.data.slice().sort((a,b)=>b.Quantity-a.Quantity);
 for(const n of [5,10,20]){await choose('Show',String(n));check(JSON.stringify(graph().data[0].x)===JSON.stringify(expected.slice(0,n).map(row=>row.Quantity)),'Northwind values '+n);}
 await choose('Show','10');button('Table').click();await wait(50);button('Quantity',document.querySelector('.chat-result')).click();await wait(50);button('Next').click();await wait(50);
 const page=document.querySelector('.chat-result-footer').textContent;button('Chart').click();await ready();check(graph().data[0].x[0]===206213,'Table sort affected ranking');button('Table').click();await wait(50);check(document.querySelector('.chat-result-footer').textContent===page,'Table page not preserved');button('Chart').click();await ready();
 check(__chartRequests===before,'Chart interaction made backend request');check(document.querySelector('.workspace-heading').textContent.includes('Customers'),'Browsing lost');check(document.querySelector('.chart-source').textContent.includes('Products')&&document.querySelector('.chart-source').textContent.includes('Order Details'),'Source lost');check(!document.querySelector('.calculation-details').open,'Calculation expanded');
 document.querySelector('.chart-keyboard').focus();return {northwindAllLimits:true,tableState:true,chartBackendRequests:__chartRequests-before};})()`));
 await call('Input.dispatchKeyEvent',{type:'keyDown',key:'ArrowRight',code:'ArrowRight',windowsVirtualKeyCode:39});
 console.log(await evaluate(`({keyboardDetail:document.querySelector('.chart-detail [role="status"]').textContent})`));
 await screenshot('northwind-desktop');
 for(const [name,type] of Object.entries({ranking:'bar',monthly:'line',scatter:'scatter',distribution:'histogram',grouped:'box',correlation:'heatmap'})){
  console.log(await evaluate(`(async()=>{await openFixture('${name}');await ready();check(document.querySelector('.result-chart-controls select').value==='${type}','Default type ${name}');check(graph()._fullLayout.paper_bgcolor==='#FFFFFF','Opaque surface');return {fixture:'${name}',type:'${type}',traces:graph().data.length};})()`));
  await screenshot(name+'-desktop');
  await call('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:false});await sleep(250);
  console.log(await evaluate(`(()=>{check(document.documentElement.scrollWidth<=390,'Page overflow');check(graph()._fullLayout.width<=390,'Chart overflow');return {narrow:'${name}',width:graph()._fullLayout.width};})()`));
  await screenshot(name+'-narrow');
  await call('Emulation.clearDeviceMetricsOverride');await sleep(150);
 }
 console.log(await evaluate(`(async()=>{
 await openFixture('scatter');await ready();await choose('Chart type','histogram');await choose('Measure','Weight');await ready();button('Table').click();await wait(50);button('Chart').click();await ready();check(document.querySelector('.result-chart-controls select').value==='histogram','Override lost');
 await openFixture('ambiguous');await wait(100);check(document.querySelector('.chart-notice').textContent.includes('Choose'),'Ambiguity not explained');check(!graph(),'Ambiguous chart guessed');
 await openFixture('empty');await wait(100);check(document.querySelector('.chart-notice').textContent.includes('no observations'),'Empty reason');button('Table').click();await wait(50);check(document.querySelector('.chat-result-footer').textContent.includes('No rows'),'Empty table unavailable');
 const start=performance.now();await openFixture('large');await ready();check(graph().data[0].x[0]===24999,'Large ranking incorrect');check(graph().data[0].x.length===10,'Too many bars');const elapsed=performance.now()-start;check(__modelRequests===0,'Model called');return {overridePreserved:true,ambiguous:true,empty:true,largeFixtureMs:elapsed,modelRequests:__modelRequests};})()`));
 console.log(await evaluate(`(async()=>{
 const input=document.querySelector('[aria-label="Question for the analyst"]');Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(input,'Captured chart workflow');input.dispatchEvent(new Event('input',{bubbles:true}));await wait(60);input.form.requestSubmit();
 await until(()=>document.querySelector('.chat-progress'),'progress missing');button('Data Preview').click();await wait(50);
 const card=await until(()=>document.querySelector('.right-panel .chat-result-card'),'completed chat card missing');
 check(document.querySelector('.workspace-heading h1').textContent==='Data Preview','Completion took over canvas');card.click();await wait(50);button('Chart').click();await ready();
 check(graph().data[0].x[0]===206213,'Chat result chart differs');check(document.querySelector('.workspace-heading').textContent.includes('Customers'),'Chat opening lost browsing context');
 check(__modelRequests===0,'Model request occurred');return {capturedProgress:true,completionPreservesCanvas:true,chatChart:true};})()`));
 if(errors.length)throw Error(errors.join('\n'));
 console.log('All chart browser checks passed. Screenshots: /tmp/chart-*.png');
} finally {ws?.close();chrome.kill();await sleep(150);await rm(profile,{recursive:true,force:true}).catch(()=>{});}
