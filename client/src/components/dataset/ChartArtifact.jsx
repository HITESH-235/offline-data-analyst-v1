import { useEffect, useRef, useState } from 'react';
import { loadPlotly } from './charts/plotly';
import { prepareGeneratedFigure } from './charts/generatedFigure';
import { useTheme } from '../../theme/ThemeContext';
import { applyPlotTheme, readChartPalette } from '../../theme/chartTheme';
const base = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000/api/v1';
function artifactUrl(path) {
  if (typeof path !== 'string' || !path.startsWith('/projects/') || path.includes('..')) return undefined;
  return base + path;
}
function Figure({ artifact, active }) {
  const { resolved } = useTheme();
  const redraw = useRef(null);
  const viewport = useRef(null), host = useRef(null);
  const [figure, setFigure] = useState(null), [error,setError] = useState(''), [note,setNote] = useState('');
  const [ready,setReady] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    const url = artifactUrl(artifact.figure_url);
    if (!url) { setError('Structured figure data is unavailable.'); return; }
    fetch(url, { signal: controller.signal }).then(response => { if (!response.ok) throw Error('The saved figure could not be loaded.'); return response.json(); })
      .then(setFigure).catch(err => { if (!controller.signal.aborted) setError(err.message); });
    return () => controller.abort();
  },[artifact]);
  useEffect(() => {
    if (!active || !figure) return;
    let disposed = false, observer, frame, lastWidth, framesAdded = false;
    const node = host.current, container = viewport.current;
    loadPlotly().then(async Plotly => {
      if (disposed) return;
      const known = Plotly.PlotSchema.get().traces;
      if (figure.data.some(trace => !known[trace.type || 'scatter'])) throw Error('This chart type is not supported by the local renderer.');
      const draw = async (force = false) => {
        if (disposed || !container.clientWidth || !force && container.clientWidth === lastWidth) return;
        lastWidth = container.clientWidth;
        const prepared = prepareGeneratedFigure(figure,lastWidth);
        setNote(prepared.note);
        const themed = applyPlotTheme(prepared, readChartPalette(), { revision: artifact.id, sourceLayout: figure.layout });
        await Plotly.react(node,themed.data,themed.layout,{ displaylogo:false, responsive:false, scrollZoom:false,
          toImageButtonOptions:{format:'png',scale:2}, modeBarButtonsToRemove:['lasso2d','select2d'] });
        if (disposed) return;
        if (prepared.frames.length && !framesAdded) { await Plotly.addFrames(node,prepared.frames); framesAdded = true; }
        setReady(true);
      };
      redraw.current = draw;
      await draw();
      if (disposed) return;
      observer = new ResizeObserver(() => { cancelAnimationFrame(frame);frame=requestAnimationFrame(() => draw().catch(err=>setError(err.message))); });
      observer.observe(container);
    }).catch(err=>{if(!disposed)setError(err.message);});
    return () => { disposed=true;observer?.disconnect();cancelAnimationFrame(frame);redraw.current=null; };
  },[active,figure]);
  useEffect(()=>{redraw.current?.(true)?.catch(err=>setError(err.message));},[resolved]);
  useEffect(()=>{const node=host.current;return()=>window.Plotly?.purge(node);},[]);
  return <>
    {error ? <p role="alert" className="chart-notice">{error} {artifact.download_url ? "Try the standalone download below." : "No standalone download was captured."}</p> : !ready && <p role="status">Loading generated figure…</p>}
    {!error && <div className="artifact-plot-scroll" ref={viewport} tabIndex={0} role="region" aria-label={`${artifact.title || 'Generated chart'}. Interactive Plotly chart; use the toolbar to zoom or reset.`}><div ref={host} /></div>}
    {note && <p className="chart-footnote">{note}</p>}
    {ready && !error && <p className="chart-footnote">Hover for values. Drag to zoom; double-click or use Reset axes to restore the view.</p>}
  </>;
}
export default function ChartArtifact({ artifacts, active }) {
  const [selected,setSelected] = useState(0);
  const artifact=artifacts[selected] || artifacts[0];
  const [imageFailed,setImageFailed]=useState(false);
  useEffect(()=>setImageFailed(false),[selected]);
  if(!artifact) return <p>No chart artifact is available.</p>;
  const download=artifactUrl(artifact.download_url), image=artifactUrl(artifact.image_url);
  return <section className="generated-artifact" aria-label="Generated chart artifact">
    {artifacts.length>1 && <label className="artifact-picker">Generated chart<select className="input-text" value={selected} onChange={event=>setSelected(Number(event.target.value))}>{artifacts.map((item,index)=><option key={item.id} value={index}>{index+1}. {item.title}</option>)}</select></label>}
    <h3 className="chart-title">{(artifact.title || 'Generated chart').replace(/<br\s*\/?>(?:\n)?/gi, ' ').replace(/<[^>]*>/g, '')}</h3>
    {artifact.kind==='plotly' && artifact.status==='ready' ? <Figure key={artifact.id} artifact={artifact} active={active}/> : artifact.kind==='png' && image && !imageFailed ? <>
      <div className="artifact-image-frame"><img style={{"--artifact-native-width": `${artifact.width || 680}px`}} src={image} alt={artifact.title || 'Generated Python chart'} onError={()=>setImageFailed(true)} /></div>
      <p className="chart-footnote">PNG image · static figure with its original aspect ratio. On narrow screens, scroll to read the full image or open it at full size.</p>
      <a className="btn btn-secondary" href={image} target="_blank" rel="noreferrer">View full-size PNG</a>
    </> : <p className="chart-notice">{imageFailed?'The saved image could not be loaded.':artifact.reason || 'This artifact cannot be previewed by the local renderer.'}</p>}
    {artifact.population?.verified && <p className="chart-footnote">Verified population: {artifact.population.count.toLocaleString()} orders, grouped by OrderID from {artifact.population.input_line_count.toLocaleString()} line items. The answer and chart use the same observations.</p>}
    {download && <a className="btn btn-secondary artifact-download" href={download} download>Download {artifact.kind==='png'?'PNG':artifact.download_format==='json'?'figure JSON':artifact.kind==='plotly'?'HTML export':'artifact'}</a>}
  </section>;
}
