// Presentation only. Never persist this view or change observations/ranges.
export function readChartPalette(root = document.documentElement) {
  const css = getComputedStyle(root);
  const value = name => css.getPropertyValue(name).trim();
  return {
    surface: value('--surface-card'), raised: value('--surface-raised'), text: value('--color-text'),
    secondary: value('--color-secondary'), grid: value('--chart-grid'), axis: value('--chart-axis'),
    hover: value('--chart-hover-bg'), hoverText: value('--chart-hover-text'), fill: value('--chart-fill'),
    negative: value('--chart-negative'), neutral: value('--chart-neutral'), positive: value('--chart-positive'),
    status: { active: value('--color-link'), success: value('--success-color'), warning: value('--warning-color'), error: value('--danger-color') },
    series: [1, 2, 3, 4, 5].map(n => value(`--chart-series-${n}`)),
  };
}

const legacy = ['#007d73', '#14212b', '#637f8d', '#9a613c', '#69865b'];
const plotlyDefaults = ['#636efa', '#ef553b', '#00cc96', '#ab63fa', '#ffa15a', '#19d3f3', '#ff6692', '#b6e880', '#ff97ff', '#fecb52'];
const defaultText = new Set(['#14212b', '#52616a', '#000', '#000000', 'black', '#fff', '#ffffff', 'white']);
const statusRoles = new Map([
  ...['success', 'succeeded', 'complete', 'completed', 'passed', 'valid', 'delivered', 'paid', 'approved'].map(s => [s, 'success']),
  ...['failed', 'failure', 'error', 'invalid', 'canceled', 'cancelled', 'rejected', 'unavailable'].map(s => [s, 'error']),
  ...['warning', 'incomplete', 'pending', 'clarification', 'needsclarification', 'unpaid', 'late'].map(s => [s, 'warning']),
  ...['running', 'processing', 'created', 'shipped', 'invoiced', 'connecting', 'classifying'].map(s => [s, 'active']),
]);
const statusRole = value => typeof value === 'string' ? statusRoles.get(value.toLowerCase().replace(/[\s_-]/g, '')) : undefined;
const knownColor = color => {
  if (typeof color !== 'string') return -1;
  const c = color.toLowerCase();
  return legacy.includes(c) ? legacy.indexOf(c) : plotlyDefaults.indexOf(c);
};
const textColor = (color, palette) => !color || defaultText.has(String(color).toLowerCase()) ? palette.text : color;
function onTraceColor(color) {
  const hex = typeof color === 'string' ? color.replace(/^#/, '') : '';
  if (!/^[\da-f]{6}$/i.test(hex)) return undefined;
  const rgb = hex.match(/../g).map(n => parseInt(n, 16) / 255).map(n => n <= .04045 ? n / 12.92 : ((n + .055) / 1.055) ** 2.4);
  const luminance = rgb[0] * .2126 + rgb[1] * .7152 + rgb[2] * .0722;
  return (1.05 / (luminance + .05)) >= ((luminance + .05) / .05) ? '#FFFFFF' : '#000000';
}

function isCorrelation(trace, layout) {
  if (trace.type !== 'heatmap') return false;
  const title = value => typeof value === 'string' ? value : value?.text || '';
  const coloraxis = layout[trace.coloraxis] || {};
  if (trace.zmin === -1 && trace.zmax === 1 || coloraxis.cmin === -1 && coloraxis.cmax === 1
    || /correlation/i.test(title(layout.title) + title(trace.colorbar?.title) + title(coloraxis.colorbar?.title))) return true;
  const z = trace.z;
  return Array.isArray(z) && z.length > 1 && z.some((row, i) => row?.[i] === 1)
    && z.every((row, i) => Array.isArray(row) && row.length === z.length && (row[i] === 1 || row[i] == null)
      && row.every((v, j) => (v == null || Number.isFinite(v) && Math.abs(v) <= 1) && v === z[j]?.[i]));
}

export function applyPlotTheme(figure, palette, { managed = false, revision, sourceLayout } = {}) {
  const data = structuredClone(figure.data), layout = structuredClone(figure.layout || {});
  const recolor = (color, index) => {
    if (managed || color == null) return palette.series[index % palette.series.length];
    const old = knownColor(color);
    return old < 0 ? color : palette.series[old % palette.series.length];
  };
  data.forEach((trace, i) => {
    const kind = trace.type || 'scatter';
    const role = statusRole(trace.meta?.status ?? trace.name);
    const semanticColor = role && palette.status?.[role];
    trace.hoverlabel = { ...trace.hoverlabel, bgcolor: palette.hover, bordercolor: palette.axis,
      font: { ...trace.hoverlabel?.font, color: palette.hoverText } };
    if (isCorrelation(trace, sourceLayout || layout)) {
      const colorscale = [[0, palette.negative], [.5, palette.neutral], [1, palette.positive]];
      Object.assign(trace, { zmin: -1, zmax: 1, zmid: 0, zauto: false,
        colorscale,
        textfont: { ...trace.textfont, color: palette.text } });
      if (trace.coloraxis) layout[trace.coloraxis] = { ...layout[trace.coloraxis], cmin: -1, cmax: 1, cmid: 0, cauto: false, colorscale };
    } else if (kind !== 'heatmap' && kind !== 'contour' && kind !== 'surface' && kind !== 'image') {
      const pointColor = ['scatter', 'scattergl', 'scatter3d', 'scatterpolar', 'bar', 'histogram', 'box', 'violin'].includes(kind) || trace.marker?.color != null;
      if (pointColor && !Array.isArray(trace.marker?.color) && typeof trace.marker?.color !== 'object') {
        trace.marker = { ...trace.marker, color: semanticColor || recolor(trace.marker?.color ?? trace.line?.color, i) };
      }
      if (Array.isArray(trace.marker?.color) && trace.marker.color.every(c => typeof c === 'string')) {
        trace.marker = { ...trace.marker, color: trace.marker.color.map((c, n) => recolor(c, n)) };
      }
      if (['pie', 'funnelarea', 'sunburst', 'treemap', 'icicle'].includes(kind)) {
        trace.marker = { ...trace.marker,
          colors: trace.marker?.colors?.map((c, n) => recolor(c, n)) || palette.series };
      }
      const categories = ['pie', 'funnelarea', 'sunburst', 'treemap', 'icicle'].includes(kind) ? trace.labels
        : kind === 'bar' ? (trace.customdata || (trace.orientation === 'h' ? trace.y : trace.x)) : null;
      if (Array.isArray(categories) && categories.length && categories.every(c => statusRole(c))) {
        const colors = categories.map(c => palette.status?.[statusRole(c)]);
        if (colors.every(Boolean)) trace.marker = { ...trace.marker, [kind === 'bar' ? 'color' : 'colors']: colors };
      }
      if (trace.line || ['scatter', 'scattergl', 'box', 'violin'].includes(kind)) {
        trace.line = { ...trace.line, color: semanticColor || recolor(trace.line?.color, i) };
      }
      if (['scatter', 'scattergl'].includes(kind) && (managed || data.length > 1)) {
        trace.marker = { ...trace.marker, symbol: trace.marker?.symbol || ({ success: 'circle', error: 'x', warning: 'diamond', active: 'square' }[role]) || ['circle', 'square', 'diamond', 'triangle-up', 'cross', 'x'][i % 6] };
        trace.line = { ...trace.line, dash: trace.line?.dash || ({ success: 'solid', error: 'dash', warning: 'dot', active: 'dashdot' }[role]) || ['solid', 'dash', 'dot', 'dashdot'][i % 4] };
      }
      if (trace.fillcolor === '#E1F1EE' || trace.fillcolor === '#e1f1ee') trace.fillcolor = palette.fill;
    }
    if (trace.outsidetextfont) trace.outsidetextfont = { ...trace.outsidetextfont, color: palette.text };
    if (kind === 'bar' || kind === 'pie') {
      const fills = kind === 'pie' ? trace.marker?.colors : trace.marker?.color;
      const choices = Array.isArray(fills) ? [...new Set(fills.map(onTraceColor))] : [onTraceColor(fills)];
      const inside = choices.length === 1 ? choices[0] : undefined;
      if (inside && (managed || !trace.insidetextfont?.color || defaultText.has(String(trace.insidetextfont.color).toLowerCase()))) {
        trace.insidetextfont = { ...trace.insidetextfont, color: inside };
      }
    }
    if (trace.textfont && kind !== 'heatmap') trace.textfont.color = textColor(trace.textfont.color, palette);
    if (trace.colorbar) trace.colorbar = { ...trace.colorbar, tickfont: { ...trace.colorbar.tickfont, color: palette.text },
      title: { ...(typeof trace.colorbar.title === 'string' ? { text: trace.colorbar.title } : trace.colorbar.title), font: { ...trace.colorbar.title?.font, color: palette.text } } };
  });
  const axis = original => ({ ...original, color: palette.text, gridcolor: palette.grid,
    zerolinecolor: palette.axis, linecolor: palette.axis,
    tickfont: { ...original?.tickfont, color: palette.text },
    title: { ...(typeof original?.title === 'string' ? { text: original.title } : original?.title), font: { ...original?.title?.font, color: palette.text } } });
  for (const key of Object.keys(layout)) {
    if (/^[xy]axis\d*$/.test(key)) layout[key] = axis(layout[key]);
    if (/^coloraxis\d*$/.test(key)) layout[key] = { ...layout[key], colorbar: { ...layout[key].colorbar,
      tickfont: { ...layout[key].colorbar?.tickfont, color: palette.text },
      title: { ...(typeof layout[key].colorbar?.title === 'string' ? { text: layout[key].colorbar.title } : layout[key].colorbar?.title),
        font: { ...layout[key].colorbar?.title?.font, color: palette.text } } } };
    if (/^scene\d*$/.test(key)) {
      layout[key] = { ...layout[key], bgcolor: palette.surface };
      for (const a of ['xaxis', 'yaxis', 'zaxis']) layout[key][a] = { ...axis(layout[key][a]), backgroundcolor: palette.raised };
    }
    if (/^(polar|ternary)\d*$/.test(key)) {
      layout[key] = { ...layout[key], bgcolor: palette.surface };
      for (const a of ['radialaxis', 'angularaxis', 'aaxis', 'baxis', 'caxis']) if (layout[key][a]) layout[key][a] = axis(layout[key][a]);
    }
  }
  layout.paper_bgcolor = palette.surface;
  layout.plot_bgcolor = palette.surface;
  layout.font = { ...layout.font, color: palette.text };
  layout.colorway = layout.colorway?.map((c, i) => recolor(c, i)) || palette.series;
  layout.legend = { ...layout.legend, bgcolor: palette.surface, font: { ...layout.legend?.font, color: palette.text } };
  layout.hoverlabel = { ...layout.hoverlabel, bgcolor: palette.hover, bordercolor: palette.axis, font: { ...layout.hoverlabel?.font, color: palette.hoverText } };
  if (layout.title) layout.title = { ...(typeof layout.title === 'string' ? { text: layout.title } : layout.title), font: { ...layout.title?.font, color: palette.text } };
  if (layout.annotations) layout.annotations = layout.annotations.map(a => ({ ...a, font: { ...a.font, color: textColor(a.font?.color, palette) },
    ...(a.bgcolor && ['white', '#fff', '#ffffff'].includes(a.bgcolor.toLowerCase()) ? { bgcolor: palette.raised } : {}) }));
  if (layout.uirevision == null && revision != null) layout.uirevision = revision;
  return { ...figure, data, layout };
}
