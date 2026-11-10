import { readFileSync } from 'node:fs';
const css = readFileSync(new URL('../../src/theme.css', import.meta.url), 'utf8');
const tokens = block => Object.fromEntries([...block.matchAll(/--([\w-]+):\s*(#[\da-f]+)/gi)].map(m => [m[1], m[2]]));
const light = tokens(css.match(/:root, :root\[data-theme="light"\]\s*\{([\s\S]*?)\}/)[1]);
export const themes = { light, dark: { ...light, ...tokens(css.match(/:root\[data-theme="dark"\]\s*\{([\s\S]*?)\}/)[1]) } };
export function palette(theme) {
  const t = themes[theme];
  return { surface:t['surface-card'], raised:t['surface-raised'], text:t['color-text'], secondary:t['color-secondary'],
    grid:t['chart-grid'], axis:t['chart-axis'], hover:t['chart-hover-bg'], hoverText:t['chart-hover-text'], fill:t['chart-fill'],
    negative:t['chart-negative'], neutral:t['chart-neutral'], positive:t['chart-positive'], series:[1,2,3,4,5].map(n=>t[`chart-series-${n}`]),
    status:{active:t['color-link'],success:t['success-color'],warning:t['warning-color'],error:t['danger-color']} };
}
export function contrast(a, b) {
  const luminance = hex => {
    const rgb = hex.slice(1).match(/../g).map(v => parseInt(v,16)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4);
    return rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722;
  };
  const x=luminance(a),y=luminance(b); return (Math.max(x,y)+.05)/(Math.min(x,y)+.05);
}

export function contrastCases() {
  const checks=[];
  for(const [name,t] of Object.entries(themes)) {
  const pairs=[];
  const pair=(fg,bg,min=4.5)=>pairs.push({fg,bg,min});
  for(const bg of ['surface-workspace','surface-card','surface-raised','surface-hover','surface-selected']) {
    for(const fg of ['color-text','color-secondary','color-link'])pair(fg,bg);
    pair('focus-color',bg,3);
  }
  for(const bg of ['surface-workspace','surface-card','surface-raised']) pair('control-border',bg,3);
  pair('action-text','action-bg');pair('action-text','action-hover');pair('selection-text','selection-bg');pair('disabled-text','disabled-bg');
  for(const state of ['success','warning']) {pair(`${state}-color`,`${state}-bg`);pair(`${state}-color`,'surface-card');pair(`${state}-color`,'surface-workspace');pair(`${state}-color`,'surface-raised');}
  pair('danger-color','error-bg');pair('danger-color','surface-card');pair('danger-color','surface-raised');
  for(const bg of ['chrome-bg','chrome-raised','chrome-hover']) {
    for(const fg of ['chrome-text','chrome-secondary','chrome-link'])pair(fg,bg);
    // Decorative dividers may be subtle; interactive boundaries must remain visible.
    pair('chrome-control-border',bg,3);pair('chrome-indicator',bg,3);pair('chrome-link',bg,3);
  }
  pair('selection-indicator','selection-bg',3);
  pair('chrome-selection-text','chrome-selection-bg');pair('chrome-indicator','chrome-selection-bg',3);pair('chrome-link','chrome-selection-bg',3);
  pair('chrome-error','chrome-error-bg');pair('chrome-error','chrome-bg');pair('image-text','image-surface');pair('chart-hover-text','chart-hover-bg');
  pair('chrome-warning','chrome-warning-bg');pair('chrome-warning','chrome-bg');pair('chrome-warning','chrome-selection-bg');
  for(const bg of ['surface-card','surface-raised']) {
    pair('chart-axis',bg,3);
    for(let n=1;n<=5;n++)pair(`chart-series-${n}`,bg,3);
  }
  for(const bg of ['chart-negative','chart-neutral','chart-positive'])pair('color-text',bg);
    for(const {fg,bg,min} of pairs) checks.push({theme:name,fg,bg,foreground:t[fg],background:t[bg],minimum:min,ratio:contrast(t[fg],t[bg])});
  }
  return checks;
}
