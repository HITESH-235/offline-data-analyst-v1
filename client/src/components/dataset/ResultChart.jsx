import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { CHART_NAMES, inspectResult, rankRows, makeChart, unitFor, escapePlotText } from './charts/chartModel';
import { loadPlotly } from './charts/plotly';

function wrapLabel(text, length = 22) {
  const words = String(text).split(/\s+/), lines = [''];
  for (const word of words) {
    const chunks = word.match(new RegExp(`.{1,${length}}`, 'gu')) || [''];
    for (const chunk of chunks) {
      const last = lines.length - 1;
      if (lines[last].length + chunk.length + 1 > length && lines[last]) lines.push(chunk);
      else lines[last] += (lines[last] ? ' ' : '') + chunk;
    }
  }
  return lines.map(escapePlotText).join('<br>');
}
function Plot({ chart, active, unit }) {
  const host = useRef(null);
  const [error, setError] = useState('');
  const [ready, setReady] = useState(false);
  const [focused, setFocused] = useState(0);
  const description = useId();
  useEffect(() => {
    if (!active) return;
    let disposed = false;
    let observer;
    const node = host.current;
    setReady(false); setError(''); setFocused(0);
    loadPlotly().then(async Plotly => {
      if (disposed) return;
      const draw = () => {
        const width = node.clientWidth;
        if (!width || disposed) return;
        const narrow = width < 500;
        const isBar = chart.type === 'bar';
        const labels = chart.rows?.map(row => wrapLabel(row.label, narrow ? 16 : 24));
        const rowHeight = isBar ? Math.max(34, ...labels.map(label => label.split('<br>').length * 14 + 12)) : 0;
        const axis = { showgrid: true, gridcolor: '#E4E4DC', zeroline: true, zerolinecolor: '#52616A', zerolinewidth: 1, automargin: true, tickfont: { size: 11 }, fixedrange: true };
        const layout = {
          width, height: isBar ? Math.max(300, rowHeight * chart.rows.length + 95) : 370,
          paper_bgcolor: '#FFFFFF', plot_bgcolor: '#FFFFFF', font: { family: 'system-ui, sans-serif', color: '#14212B', size: 12 },
          margin: { l: isBar ? (narrow ? 125 : 175) : 60, r: chart.type === 'heatmap' ? 65 : 24, t: 20, b: 65 },
          showlegend: false, hovermode: 'closest', dragmode: false, bargap: .32,
          xaxis: { ...axis, title: { text: escapePlotText(chart.xLabel === unit ? unit : `${chart.xLabel}${unit && ['bar', 'histogram'].includes(chart.type) ? ` (${unit})` : ''}`), standoff: 12 },
            ...(isBar ? { rangemode: 'tozero', tickformat: '~s', nticks: narrow ? 4 : 6 } : {}),
            ...(chart.type === 'line' ? { type: 'date', nticks: narrow ? 4 : 7 } : {}) },
          yaxis: { ...axis, title: { text: isBar ? '' : escapePlotText(`${chart.yLabel}${unit && ['line','scatter','box'].includes(chart.type) && unit !== chart.yLabel ? ` (${unit})` : ''}`), standoff: 10 },
            ...(isBar ? { tickmode: 'array', tickvals: chart.rows.map((_, i) => i), ticktext: labels, autorange: 'reversed', showgrid: false, zeroline: false } : {}),
            ...(chart.type === 'histogram' ? { rangemode: 'tozero', tickformat: ',d', nticks: 6 } : {}) },
        };
        return Plotly.react(node, chart.traces, layout, { displayModeBar: false, responsive: false, scrollZoom: false, displaylogo: false });
      };
      await draw();
      if (disposed) { Plotly.purge(node); return; }
      setReady(true);
      observer = new ResizeObserver(() => { draw()?.catch(() => setError('Could not resize this chart. Table is still available.')); });
      observer.observe(node);
    }).catch(err => { if (!disposed) setError(err.message); });
    return () => { disposed = true; observer?.disconnect(); };
  }, [chart, active, unit]);
  useEffect(() => { const node = host.current; return () => { if (window.Plotly && node) window.Plotly.purge(node); }; }, []);
  return <>
    {error && <p role="alert">{error}</p>}
    {!ready && !error && <p role="status">Loading chart…</p>}
    <div className="chart-keyboard" tabIndex={0} role="group" aria-label={`${chart.title}. Use left and right arrow keys to inspect values.`} aria-describedby={description}
      onKeyDown={event => {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        setFocused(value => event.key === 'Home' ? 0 : event.key === 'End' ? chart.details.length - 1 : Math.max(0, Math.min(chart.details.length - 1, value + (event.key === 'ArrowRight' ? 1 : -1))));
      }}>
      <div ref={host} className="plotly-result" aria-hidden="true" />
    </div>
    <div className="chart-detail" id={description}>
      <span className="chart-detail-hint">Hover for values · Focus chart and use ← → to inspect</span>
      <span role="status" aria-live="polite">{chart.details[focused]}{unit ? ` · ${unit}` : ''}</span>
    </div>
  </>;
}

function ChartExplorer({ result, snapshot, active, model }) {
  const [type, setType] = useState(model.preferred);
  const [fields, setFields] = useState(model.initial);
  const [limit, setLimit] = useState(10);
  const { x, y } = fields;
  // Top N only slices this cached ranking; table sorting and pagination never enter it.
  const ranking = useMemo(() => type === 'bar' && x && y ? rankRows(model.data, x, y) : [], [model.data, type, x, y]);
  const chart = useMemo(() => makeChart(model, type, x, y, ranking, limit), [model, type, x, y, ranking, limit]);
  const pairs = model.choices[type] || [];
  const xs = [...new Set(pairs.map(pair => pair.x))];
  const ys = [...new Set(pairs.filter(pair => !x || pair.x === x).map(pair => pair.y))];
  const unit = unitFor(result, type === 'histogram' ? x : y);
  const changeType = value => {
    setType(value);
    const options = model.choices[value];
    const previous = options.find(pair => pair.x === x && pair.y === y);
    setFields(previous || (options.length === 1 ? options[0] : { x: '', y: '' }));
  };
  if (!model.types.length) return <p className="chart-notice">Chart unavailable. {model.data.length ? `There is no supported combination of non-ID fields.${model.aggregated ? ' Aggregated values cannot supply a raw distribution.' : ' Confirm raw observations below only if these rows are individual records.'}` : 'This result has no observations.'} Table remains available.</p>;
  return <>
    <div className="result-chart-controls">
      <label>Chart type<select className="input-text" value={type} onChange={event => changeType(event.target.value)}>{model.types.map(value => <option key={value} value={value}>{CHART_NAMES[value]}</option>)}</select></label>
      {type !== 'heatmap' && <label>{type === 'line' ? 'Date / time' : type === 'histogram' ? 'Measure' : ['bar','box'].includes(type) ? 'Category' : 'X measure'}
        <select className="input-text" value={x} onChange={event => { const nextX = event.target.value; const eligible = pairs.filter(pair => pair.x === nextX); setFields({ x: nextX, y: eligible.some(pair => pair.y === y) ? y : eligible.length === 1 ? eligible[0].y : '' }); }}>
          <option value="">Choose a field</option>{xs.map(value => <option key={value}>{value}</option>)}
        </select></label>}
      {!['heatmap','histogram'].includes(type) && <label>{type === 'scatter' ? 'Y measure' : 'Numeric measure'}<select className="input-text" value={y} onChange={event => setFields({ x, y: event.target.value })}>
        <option value="">Choose a field</option>{ys.map(value => <option key={value}>{value}</option>)}
      </select></label>}
      {type === 'bar' && <label>Show<select className="input-text" value={limit} onChange={event => setLimit(Number(event.target.value))}>{[5,10,20].map(n => <option key={n} value={n}>Top {n}</option>)}</select></label>}
    </div>
    <p className="chart-reason">Default: {CHART_NAMES[model.preferred]}. {model.reason}{type !== model.preferred ? ` You selected ${CHART_NAMES[type].toLowerCase()}.` : ''}</p>
    {!chart ? <p className="chart-notice">Several fields could fit. Choose the fields you want to compare.</p> : <>
      <h3 className="chart-title">{chart.title}</h3>
      <p className="chart-source">Source: {snapshot.tables?.join(' · ') || 'Source unavailable'}</p>
      <Plot chart={chart} active={active} unit={unit === y || unit === x ? '' : unit} />
      {chart.omitted > 0 && <p className="chart-notice">{chart.omitted.toLocaleString()} rows without usable values in the selected fields were omitted.</p>}
      {type === 'bar' && <p className="chart-footnote">Ranked across the full result. Zero baseline; no categories combined.</p>}
      {type === 'line' && <p className="chart-footnote">All usable dates, ordered chronologically. Missing values are omitted; no dates are filled in.</p>}
      {type === 'box' && <p className="chart-footnote">Linear-interpolated quartiles; whiskers stop at observations within 1.5 × IQR. Dots show outliers.</p>}
    </>}
  </>;
}
export default function ResultChart({ result, snapshot = {}, active = true }) {
  const [meaning, setMeaning] = useState('');
  const model = useMemo(() => inspectResult(result, snapshot.calculation, snapshot.question, meaning), [result, snapshot.calculation, snapshot.question, meaning]);
  return <section className="result-chart" aria-label="Result chart exploration">
    <ChartExplorer key={meaning} result={result} snapshot={snapshot} active={active} model={model} />
    {model.ids.length > 0 && <p className="chart-footnote">Identifier fields excluded: {model.ids.join(', ')}.</p>}
    {model.duplicateCategories && <p className="chart-footnote">Repeated categories cannot be ranked without a grouping calculation; rows have not been combined.</p>}
    {!model.aggregated && model.data.length > 0 && <label className="chart-meaning">What do these rows represent?<select className="input-text" value={meaning} onChange={event => setMeaning(event.target.value)}>
      <option value="">{model.raw ? 'Raw observations (from analysis)' : 'Not specified'}</option><option value="raw">Raw individual observations</option><option value="summary">Summarized values</option>
    </select><span>Distribution and box charts require raw observations.</span></label>}
  </section>;
}
