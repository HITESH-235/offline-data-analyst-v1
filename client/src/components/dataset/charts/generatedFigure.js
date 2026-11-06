// Presentation changes only; trace values, scales, annotations, and series survive.
const INK = '#14212B', TEAL = '#007D73';
const titleText = title => typeof title === 'string' ? title : title?.text || '';
export function prepareGeneratedFigure(figure, width) {
  if (!figure || !Array.isArray(figure.data) || !figure.data.length) throw Error('This figure contains no data traces.');
  const emptyArray = value => value == null || (Array.isArray(value) && value.every(item => item == null || (Array.isArray(item) && item.length === 0))) || (typeof value === 'object' && 'bdata' in value && !value.bdata);
  const pointTraces = new Set(['scatter','scattergl','bar','histogram','box','violin']);
  const data = structuredClone(figure.data), original = structuredClone(figure.layout || {});
  const unsafe = new Set(['scattermap','scattermapbox','choroplethmap','choroplethmapbox','densitymap','densitymapbox','scattergeo','choropleth']);
  if (data.some(trace => unsafe.has(trace.type) || typeof trace.geojson === 'string' || (trace.type === 'image' && trace.source && !/^data:image\/(png|jpeg);base64,/.test(trace.source)))) throw Error('This figure needs external map or image resources. Use the standalone download; no remote resources are loaded in Result.');
  const images = original.images || [];
  if (images.some(image => !/^data:image\/(png|jpeg);base64,/.test(image.source || ''))) throw Error('This figure includes an external image. Use the download to inspect it separately.');
  if (figure.data.every(trace => pointTraces.has(trace.type || 'scatter') && ['x','y','q1','median','q3'].every(key => emptyArray(trace[key])))) {
    throw Error('This saved chart contains no plotted observations. The calculation produced an empty result; check its filters and date parsing, then rerun the analysis.');
  }
  const narrow = width < 520;
  const wrap = (text, length) => {
    if (typeof text !== 'string' || text.includes('<')) return text;
    const lines=[''];
    for(const word of text.split(/\s+/)) {
      if(lines[lines.length-1].length + word.length + 1 > length) lines.push(word);
      else lines[lines.length-1] += (lines[lines.length-1] ? ' ' : '') + word;
    }
    return lines.join('<br>');
  };
  if(narrow) data.forEach(trace => { if(trace.name) trace.name=wrap(trace.name,28); });
  const numericAxes = new Set();
  data.forEach(trace => {
    if (trace.type === 'bar' && !trace.base) numericAxes.add(trace.orientation === 'h' ? (trace.xaxis || 'x') : (trace.yaxis || 'y'));
  });
  const layout = { ...original, template: undefined, autosize: false, width,
    height: Math.max(380, Math.min(650, Number(original.height) || 440)),
    paper_bgcolor: '#FFFFFF', plot_bgcolor: '#FFFFFF',
    font: { family: 'system-ui, sans-serif', size: narrow ? 11 : 12, color: INK, ...original.font },
    colorway: original.colorway || [TEAL, INK, '#637F8D', '#9A613C', '#69865B'],
    margin: { l: narrow ? 60 : 75, r: 25, t: 55, b: 85, ...original.margin, autoexpand: true },
    // The full title is rendered once as an accessible Result heading, outside the zoom toolbar.
    title: { text: '' },
    legend: { orientation: 'h', x: 0, y: -0.3, xanchor: 'left', yanchor: 'top', ...original.legend,
      ...(narrow ? { orientation: 'h', x: 0, y: -0.35, xanchor: 'left', yanchor: 'top' } : {}),
      bgcolor: '#FFFFFF', font: { size: 11, color: INK, ...original.legend?.font } },
    hoverlabel: { bgcolor: INK, font: { color: '#FFFFFF' }, ...original.hoverlabel },
  };
  // Explicit user zoom/ranges and logarithmic scales are retained.
  for (const name of new Set(['xaxis', 'yaxis', ...Object.keys(original).filter(key => /^[xy]axis\d*$/.test(key))])) {
    const axis = original[name] || {};
    const text = titleText(axis.title);
    const styled = { gridcolor: '#E4E4DC', zerolinecolor: '#52616A', automargin: true, ...axis,
      tickfont: { size: narrow ? 10 : 11, color: INK, ...axis.tickfont },
      title: { ...(typeof axis.title === 'object' ? axis.title : { text: axis.title }), standoff: axis.title?.standoff ?? 14 },
    };
    if (/month/i.test(text) && !axis.tickformat) { styled.tickformat = '%b %Y'; styled.dtick = 'M1'; }
    if (numericAxes.has(name.replace('axis','')) && !axis.range && axis.type !== 'log') styled.rangemode = 'tozero';
    if (/\b(USD|dollars?)\b|\$/.test(text) && !axis.tickformat) { styled.tickprefix = '$'; styled.tickformat = '~s'; styled.hoverformat = axis.hoverformat || ',.2f'; }
    else if (/quantity|units|revenue|count/i.test(text) && !axis.tickformat) styled.tickformat = '~s';
    layout[name] = styled;
  }
  let scrollWidth = width, note = '';
  for (const trace of data) {
    const horizontal = trace.type === 'bar' && trace.orientation === 'h';
    const categories = horizontal ? trace.y : trace.x;
    if (Array.isArray(categories) && categories.some(value => typeof value === 'string') && !categories.every(value => /^\d{4}-\d\d(?:-\d\d)?/.test(String(value)))) {
      const longest = Math.max(...categories.map(value => String(value).length), 0);
      if (horizontal) {
        layout.height = Math.max(layout.height, categories.length * Math.min(80, Math.max(30, longest / 22 * 14)) + 130);
        layout.margin.l = Math.min(Math.max(layout.margin.l, 160), Math.round(width*.45));
      } else if (categories.length > 12 || longest > 20) {
        scrollWidth = Math.max(scrollWidth, categories.length * Math.min(100, Math.max(45, longest * 3)) + 160);
        layout.xaxis.tickangle = layout.xaxis.tickangle ?? -35;
        layout.margin.b = Math.max(layout.margin.b, Math.min(210, longest * 4));
        note = 'All categories are included. Scroll horizontally to read dense labels; no data is omitted.';
      }
    }
  }
  if (data.filter(trace => trace.showlegend !== false && trace.name).length > 6) layout.height += 90;
  layout.width = scrollWidth;
  return { data, layout, frames: figure.frames || [], note, scrollWidth };
}
