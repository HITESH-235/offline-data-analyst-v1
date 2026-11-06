// Pure, deterministic result inspection. Never infer measures from numeric strings.
export const CHART_NAMES = { bar: 'Bar', line: 'Line', scatter: 'Scatter', histogram: 'Histogram', box: 'Box', heatmap: 'Heatmap' };
const present = value => value !== null && value !== undefined && value !== '';
export const formatValue = value => typeof value === 'number'
  ? value.toLocaleString(undefined, { maximumFractionDigits: 20 }) : String(value);
export const isIdentifier = name => /(^id$|[_ .]id$|ID$|Id$|identifier|postal|zip.?code)/.test(name);

export function dateValue(value) {
  if (typeof value !== 'string') return null;
  // Reject ambiguous locale dates; validate calendar components before parsing.
  const match = /^(\d{4})-(\d{2})(?:-(\d{2}))?(?:T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2}))?$/.exec(value);
  if (!match) return null;
  const [, year, month, day = '01'] = match;
  const date = new Date(Date.UTC(+year, +month - 1, +day));
  if (date.getUTCFullYear() !== +year || date.getUTCMonth() !== +month - 1 || date.getUTCDate() !== +day) return null;
  const timestamp = value.includes('T') ? Date.parse(value) : date.getTime();
  return Number.isFinite(timestamp) ? timestamp : null;
}

export function inspectResult(result, calculation, question = '', meaning = '') {
  const data = Array.isArray(result?.data) ? result.data : [];
  const columns = Array.isArray(result?.columns) ? result.columns : [];
  const steps = calculation?.steps?.filter(step => step.status === 'succeeded') || [];
  const aggregated = steps.some(step => ['aggregation', 'statistics', 'correlation'].includes(step.tool)) || columns.some(column => /^(sum|avg|mean|count)[_( ]|^total/i.test(column)) || /\b(grouped by|group by|summed|aggregated totals)\b/i.test(question);
  const raw = !aggregated && meaning !== 'summary' && (meaning === 'raw' || steps.some(step => step.tool === 'filtering') || /\b(raw|individual) (observations|records|rows)\b/i.test(question));
  const categories = [], numbers = [], dates = [], ids = [];
  for (const column of columns) {
    const values = data.map(row => row[column]).filter(present);
    const declared = String(result?.data_types?.[column] ?? result?.column_types?.[column] ?? '').toLowerCase();
    if (isIdentifier(column) || /identifier|primary.?key/.test(declared)) { ids.push(column); continue; }
    if (!values.length) continue;
    if (/date|time/.test(declared)) {
      if (values.every(value => dateValue(value) !== null)) dates.push(column);
      continue; // Epoch units or ambiguous strings need clarification, not guessing.
    }
    if (/category|categorical|enum/.test(declared) && values.every(value => typeof value === 'string' || typeof value === 'boolean' || Number.isFinite(value))) categories.push(column);
    else if (values.every(Number.isFinite)) numbers.push(column);
    else if (values.every(value => dateValue(value) !== null)) dates.push(column);
    else if (values.every(value => typeof value === 'string' || typeof value === 'boolean')) categories.push(column);
  }
  let matrix = null;
  const corr = result?.correlation;
  if (corr?.columns?.length >= 2 && corr.matrix?.length === corr.columns.length &&
      corr.matrix.every(row => Array.isArray(row) && row.length === corr.columns.length && row.every(value => value == null || (Number.isFinite(value) && Math.abs(value) <= 1)))) {
    matrix = corr;
  } else if (steps.some(step => step.tool === 'correlation') && categories.length === 1 && numbers.length >= 2) {
    const label = categories[0];
    if (data.length === numbers.length && numbers.every(name => data.filter(row => row[label] === name).length === 1)) {
      const values = numbers.map(name => numbers.map(col => data.find(row => row[label] === name)[col]));
      if (values.every(row => row.every(value => value == null || (Number.isFinite(value) && Math.abs(value) <= 1)))) matrix = { columns: numbers, matrix: values };
    }
  }
  if (matrix) {
    const kept = matrix.columns.map((name, index) => ({ name, index })).filter(({ name }) => !isIdentifier(name));
    matrix = kept.length >= 2 ? { columns: kept.map(({ name }) => name), matrix: kept.map(({ index }) => kept.map(item => matrix.matrix[index][item.index])) } : null;
  }
  const pairs = (xs, ys, validX) => xs.flatMap(x => ys.filter(y => y !== x && data.some(row => validX(row[x]) && Number.isFinite(row[y]))).map(y => ({ x, y })));
  const categoryPairs = pairs(categories, numbers, value => present(value));
  const bar = categoryPairs.filter(({ x, y }) => {
    const labels = data.filter(row => present(row[x]) && Number.isFinite(row[y])).map(row => String(row[x]));
    return new Set(labels).size === labels.length;
  });
  const line = pairs(dates, numbers, value => dateValue(value) !== null).filter(({ x, y }) => {
    const times = data.filter(row => dateValue(row[x]) !== null && Number.isFinite(row[y])).map(row => dateValue(row[x]));
    return times.length >= 2 && new Set(times).size === times.length;
  });
  const scatter = pairs(numbers, numbers, Number.isFinite);
  const box = raw ? categoryPairs.filter(({ x, y }) => {
    const counts = new Map();
    data.forEach(row => { if (present(row[x]) && Number.isFinite(row[y])) counts.set(String(row[x]), (counts.get(String(row[x])) || 0) + 1); });
    return counts.size > 0 && [...counts.values()].every(count => count >= 2);
  }) : [];
  const histogram = raw ? numbers.filter(column => data.filter(row => Number.isFinite(row[column])).length >= 2).map(x => ({ x, y: '' })) : [];
  const choices = { bar, line, scatter, histogram, box, heatmap: matrix ? [{ x: '', y: '' }] : [] };
  const types = Object.keys(choices).filter(type => choices[type].length);
  let preferred = matrix ? 'heatmap' : line.length ? 'line' : box.length ? 'box' : bar.length ? 'bar' : scatter.length ? 'scatter' : histogram.length ? 'histogram' : '';
  // More than two numeric columns require a deliberate choice, not an arbitrary pair.
  const initial = preferred && (choices[preferred].length === 1 || (preferred === 'scatter' && numbers.length === 2)) ? choices[preferred][0] : { x: '', y: '' };
  const reasons = {
    bar: 'A category and a numeric measure make a ranking easy to compare.',
    line: 'Dates and a numeric measure show change over time, in chronological order.',
    scatter: 'Two numeric measures show how individual values relate.',
    histogram: 'Raw numeric observations can show the shape of a distribution.',
    box: 'Repeated raw observations in each category can show spread and median.',
    heatmap: 'A supplied correlation matrix shows relationships between measures.',
  };
  return { data, columns, categories, numbers, dates, ids, aggregated, raw, matrix, choices, types, preferred, initial, reason: reasons[preferred], unknownMeaning: !aggregated && !raw, duplicateCategories: categoryPairs.length > bar.length };
}

export function rankRows(data, x, y) {
  const top = [];
  for (let index = 0; index < data.length; index++) {
    const row = data[index];
    if (!present(row[x]) || !Number.isFinite(row[y])) continue;
    if (top.length === 20 && row[y] <= top[19].value) continue;
    const entry = { label: String(row[x]), value: row[y], index };
    const at = top.findIndex(other => entry.value > other.value);
    top.splice(at < 0 ? top.length : at, 0, entry);
    if (top.length > 20) top.pop();
  }
  return top;
}
export function unitFor(result, column) {
  if (typeof result?.units?.[column] === 'string') return result.units[column];
  if (/^(quantity|units)$/i.test(column)) return 'units';
  return column;
}
const escape = text => String(text).replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
const quantile = (values, q) => { const n = (values.length - 1) * q, low = Math.floor(n); return values[low] + (values[Math.ceil(n)] - values[low]) * (n - low); };

export function makeChart(model, type, x, y, ranking, limit = 10) {
  if (!model.choices[type]?.some(pair => pair.x === x && pair.y === y)) return null;
  const teal = '#007D73';
  const base = { marker: { color: teal }, hoverlabel: { bgcolor: '#14212B', font: { color: '#FFFFFF' } } };
  let traces = [], details = [], title = '', xLabel = x, yLabel = y, omitted = 0;
  if (type === 'bar') {
    const rows = ranking.slice(0, limit);
    details = rows.map(row => `${row.label}: ${formatValue(row.value)}`);
    title = `Top ${rows.length} ${x} by ${y}`;
    xLabel = y; yLabel = x;
    traces = [{ ...base, type: 'bar', orientation: 'h', x: rows.map(row => row.value), y: rows.map((_, i) => i),
      text: rows.map(row => formatValue(row.value)), textposition: rows.map(row => row.value === 0 ? 'outside' : 'auto'), cliponaxis: false, outsidetextfont: { color: '#14212B' }, customdata: rows.map(row => escape(row.label)),
      hovertemplate: '%{customdata}<br>%{x:,}<extra></extra>' }];
    omitted = model.data.length - model.data.filter(row => present(row[x]) && Number.isFinite(row[y])).length;
    return { traces, details, title, xLabel, yLabel, omitted, rows, type };
  }
  if (type === 'line' || type === 'scatter') {
    const rows = model.data.map((row, index) => ({ x: type === 'line' ? dateValue(row[x]) : row[x], y: row[y], label: row[x], index }))
      .filter(row => Number.isFinite(row.x) && Number.isFinite(row.y));
    if (type === 'line') rows.sort((a, b) => a.x - b.x);
    details = rows.map(row => `${x}: ${formatValue(row.label)} · ${y}: ${formatValue(row.y)}`);
    title = type === 'line' ? `${y} over time` : `${y} versus ${x}`;
    traces = [{ ...base, type: 'scatter', mode: type === 'line' ? 'lines+markers' : 'markers',
      x: rows.map(row => type === 'line' ? new Date(row.x).toISOString() : row.x), y: rows.map(row => row.y),
      line: { color: teal, width: 2 }, marker: { color: teal, size: 7, opacity: .85 },
      customdata: details.map(escape), hovertemplate: '%{customdata}<extra></extra>' }];
    omitted = model.data.length - rows.length;
  } else if (type === 'histogram') {
    const values = model.data.map(row => row[x]).filter(Number.isFinite);
    const min = values.reduce((a, b) => Math.min(a, b), Infinity), max = values.reduce((a, b) => Math.max(a, b), -Infinity);
    const count = min === max ? 1 : Math.min(30, Math.ceil(Math.sqrt(values.length)));
    const width = min === max ? Math.max(1, Math.abs(min) * .05) : (max - min) / count;
    const start = min === max ? min - width / 2 : min;
    const bins = Array.from({ length: count }, (_, i) => ({ low: start + i * width, high: start + (i + 1) * width, count: 0 }));
    values.forEach(value => bins[Math.min(count - 1, Math.floor((value - start) / width))].count++);
    details = bins.map((bin, i) => `${formatValue(bin.low)} to ${formatValue(bin.high)} (${i === count - 1 ? 'upper bound included' : 'upper bound excluded'}): ${bin.count} observations`);
    title = `Distribution of ${x}`; yLabel = 'Observations';
    traces = [{ ...base, type: 'bar', x: bins.map(bin => (bin.low + bin.high) / 2), y: bins.map(bin => bin.count), width: width * .96,
      customdata: details.map(escape), hovertemplate: '%{customdata}<extra></extra>' }];
    omitted = model.data.length - values.length;
  } else if (type === 'box') {
    const groups = new Map();
    model.data.forEach(row => { if (present(row[x]) && Number.isFinite(row[y])) { const key = String(row[x]); if (!groups.has(key)) groups.set(key, []); groups.get(key).push(row[y]); } else omitted++; });
    const rows = [...groups].map(([label, values]) => {
      values.sort((a, b) => a - b);
      const q1 = quantile(values, .25), median = quantile(values, .5), q3 = quantile(values, .75), iqr = q3 - q1;
      return { label, q1, median, q3, low: Math.min(q1, values.find(value => value >= q1 - 1.5 * iqr)), high: Math.max(q3, values.findLast(value => value <= q3 + 1.5 * iqr)), values };
    });
    details = rows.map(row => `${row.label}: ${row.values.length} observations; Q1 ${formatValue(row.q1)}, median ${formatValue(row.median)}, Q3 ${formatValue(row.q3)}; whiskers ${formatValue(row.low)} to ${formatValue(row.high)}`);
    title = `${y} distribution by ${x}`;
    traces = [{ ...base, type: 'box', x: rows.map(row => escape(row.label)), q1: rows.map(row => row.q1), median: rows.map(row => row.median), q3: rows.map(row => row.q3),
      lowerfence: rows.map(row => row.low), upperfence: rows.map(row => row.high), boxpoints: false, line: { color: teal }, fillcolor: '#E1F1EE', name: y,
      customdata: details.map(escape), hovertemplate: '%{customdata}<extra></extra>' },
      { ...base, type: 'scatter', mode: 'markers', x: rows.flatMap(row => row.values.filter(v => v < row.low || v > row.high).map(() => escape(row.label))),
        y: rows.flatMap(row => row.values.filter(v => v < row.low || v > row.high)), name: 'Outliers', hovertemplate: '%{x}: %{y:,}<extra>Outlier</extra>' }];
  } else if (type === 'heatmap') {
    const { columns, matrix } = model.matrix;
    title = 'Correlation between measures'; xLabel = 'Measure'; yLabel = 'Measure';
    details = matrix.flatMap((row, i) => row.map((value, j) => `${columns[i]} × ${columns[j]}: ${value == null ? 'unavailable' : formatValue(value)}`));
    traces = [{ type: 'heatmap', x: columns.map(escape), y: columns.map(escape), z: matrix, zmin: -1, zmax: 1,
      colorscale: [[0, '#975437'], [.5, '#F5F3EE'], [1, teal]], colorbar: { title: { text: 'Correlation' }, thickness: 12 },
      hovertemplate: '%{y} × %{x}: %{z:.4f}<extra></extra>', hoverongaps: false }];
  }
  return { traces, details, title, xLabel, yLabel, omitted, type };
}
export { escape as escapePlotText };
