import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
import { contrastCases } from './fixtures/themeTokens.mjs';

const html=readFileSync(new URL('../index.html',import.meta.url),'utf8');
const script=html.match(/<script id="theme-init">([\s\S]*?)<\/script>/)[1];
function boot(saved, dark=false, blocked=false) {
  const storage=new Map(saved ? [['analyst-theme',saved]]:[]),events={};
  const media={matches:dark,addEventListener:(name,fn)=>events.media=fn};
  const root={dataset:{},style:{}};
  const window={matchMedia:()=>media,addEventListener:(name,fn)=>events[name]=fn,localStorage:{
    getItem:key=>{if(blocked)throw Error('disabled');return storage.get(key)??null;},
    setItem:(key,value)=>{if(blocked)throw Error('disabled');storage.set(key,value);},
  }};
  vm.runInNewContext(script,{window,document:{documentElement:root}});
  return {store:window.analystTheme,root,storage,events,media};
}
test('blocking bootstrap applies saved preference before app mount',()=>{
  const {root,store}=boot('dark');assert.equal(root.dataset.theme,'dark');assert.equal(root.style.colorScheme,'dark');assert.equal(store.getSnapshot().preference,'dark');
  assert.ok(html.indexOf('id="theme-init"')<html.indexOf('<body>'));assert.doesNotMatch(html.match(/<script id="theme-init">/)[0],/defer|async|src=/);
});
test('initial system resolution is saved and does not keep following the OS',()=>{
  const b=boot(null,true);assert.equal(b.root.dataset.theme,'dark');assert.equal(b.storage.get('analyst-theme'),'dark');
  assert.equal(b.events.media,undefined);b.media.matches=false;assert.equal(b.root.dataset.theme,'dark');
  let updates=0;const off=b.store.subscribe(()=>updates++);
  b.store.setPreference('light');assert.equal(b.root.dataset.theme,'light');assert.equal(b.storage.get('analyst-theme'),'light');
  b.store.setPreference('dark');assert.equal(b.root.dataset.theme,'dark');assert.equal(updates,2);
  off();b.store.setPreference('light');assert.equal(updates,2);
  assert.equal(boot(b.storage.get('analyst-theme'),true).root.dataset.theme,'light');
});
test('saved System migrates once to the resolved Light or Dark choice',()=>{
  for(const dark of [true,false]) {
    const b=boot('system',dark),expected=dark?'dark':'light';
    assert.equal(b.store.getSnapshot().preference,expected);assert.equal(b.storage.get('analyst-theme'),expected);
    assert.equal(b.root.dataset.themePreference,expected);
    assert.equal(boot(b.storage.get('analyst-theme'),!dark).root.dataset.theme,expected);
  }
});
test('invalid preferences, blocked storage and cross-tab updates remain usable',()=>{
  assert.equal(boot('unknown',true).root.dataset.theme,'dark');const b=boot(null,false,true);b.store.setPreference('dark');assert.equal(b.root.dataset.theme,'dark');
  const c=boot('light');c.storage.set('analyst-theme','dark');c.events.storage({key:'analyst-theme'});assert.equal(c.root.dataset.theme,'dark');
  c.storage.clear();c.events.storage({key:null});assert.equal(c.store.getSnapshot().preference,'light');assert.equal(c.storage.get('analyst-theme'),'light');
});
test('semantic styles and favicon contain no old neon selection or purple theme tokens',()=>{
  const css=readFileSync(new URL('../src/theme.css',import.meta.url),'utf8');
  const icon=readFileSync(new URL('../public/favicon.svg',import.meta.url),'utf8');
  assert.doesNotMatch(css+icon,/#(?:DFFF00|56268A|BDA1FF|211329)/i);
});

for(const name of ['light','dark']) {
  test(`${name} actual text/control/chart token pairs meet contrast targets`,()=>{
    for(const c of contrastCases().filter(c=>c.theme===name)) {
      assert.ok(c.ratio>=c.minimum,`${name} ${c.fg} ${c.foreground} on ${c.bg} ${c.background}: ${c.ratio.toFixed(2)} < ${c.minimum}`);
    }
  });
}
