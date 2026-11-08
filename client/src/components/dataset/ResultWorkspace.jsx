import { Table2, ChartBar } from "lucide-react";
import { useState } from "react";
import CalculationDetails from "../chat/CalculationDetails";
import ResultTable from "../chat/ResultTable";
import ChartArtifact from "./ChartArtifact";
import ResultChart from "./ResultChart";
import { calculationOutputs, chartsForOutput } from "./analysisPackage";

function OutputCharts({ table, snapshot, charts, active }) {
  const choices=chartsForOutput({charts},table.id);
  const [chosen,setChosen]=useState(choices[0]?.id);
  const [visited,setVisited]=useState([choices[0]?.id]);
  const current=choices.find(c=>c.id===chosen) || choices[0];
  return <>
    {choices.length>1 && <label>Chart<select className="input-text" value={current.id} onChange={e=>{setChosen(e.target.value);setVisited(previous=>previous.includes(e.target.value)?previous:[...previous,e.target.value]);}}>{choices.map((c,i)=><option key={c.id} value={c.id}>{c.specification?.title || `Chart ${i+1}`}</option>)}</select></label>}
    {choices.filter(c=>visited.includes(c.id)).map(c=><div key={c.id} hidden={c.id!==current.id}><ResultChart result={table.result} snapshot={{...snapshot,tables:table.source?.tables || snapshot.tables,chartSpec:c.specification}} active={active&&c.id===current.id}/></div>)}
    {!snapshot.analysisPackage && <ResultChart result={table.result} snapshot={snapshot} active={active}/>}
    {snapshot.analysisPackage && !choices.length && <p>No compatible chart was established for this output. Table remains available.</p>}
  </>;
}

export default function ResultWorkspace({ snapshot }) {
  const pack=snapshot.analysisPackage;
  const tables=calculationOutputs(snapshot);
  const [selected,setSelected]=useState(tables[0]?.id);
  const table=tables.find(t=>t.id===selected) || tables[0];
  const [view,setView]=useState(table?'Table':'Chart');
  const [opened,setOpened]=useState([]);
  const artifacts=snapshot.artifacts || [];
  const charts=pack?.charts?.filter(c=>c.kind==='result') || [];
  return <section className="result-workspace" aria-label="Analysis result">
    {snapshot.question && <p className="result-question"><strong>Question</strong> {snapshot.question}</p>}
    {pack && <p role="status" className="chart-source">Analysis: {pack.status}{pack.status!=='complete' ? ` · ${pack.incomplete_reasons.join(' ')}` : ' · Declared calculation requirements completed'}</p>}
    {tables.length>1 && <label>Calculation output<select className="input-text" value={table?.id} onChange={e=>{setSelected(e.target.value);if(view==='Chart')setOpened(previous=>previous.includes(e.target.value)?previous:[...previous,e.target.value]);}}>{tables.map(t=><option key={t.id} value={t.id}>{t.label}{t.completion_status === "incomplete" ? " (incomplete)" : ""}</option>)}</select></label>}
    <div className="workspace-toolbar result-toolbar" role="group" aria-label="Result view">
      {(table?['Table','Chart']:['Chart']).map(label=><button key={label} type="button" className={`btn ${view===label?'btn-primary':'btn-secondary'}`} aria-pressed={view===label} onClick={()=>{setView(label);if(label==='Chart'&&table)setOpened(previous=>previous.includes(table.id)?previous:[...previous,table.id]);}}>
        {label==='Table'?<Table2 size={14}/>:<ChartBar size={14}/>} {label}
      </button>)}
      <span className="result-dimensions">{table?`${table.result.data.length.toLocaleString()} rows / ${table.result.columns.length} columns`:`${artifacts.length} captured exports`}</span>
    </div>
    {tables.map(t=><div key={t.id} hidden={table?.id!==t.id}>
      <p className="chart-source">Source: {t.source?.tables?.join(' · ') || snapshot.tables?.join(' · ') || 'Unavailable'}{t.result.source_observation_count!=null?` · Source observations: ${t.result.source_observation_count.toLocaleString()}`:''}</p>
      <div hidden={view!=='Table'}><ResultTable result={t.result}/></div>
      {opened.includes(t.id) && <div hidden={view!=='Chart'}>
        <OutputCharts table={t} charts={charts} snapshot={{...snapshot,chartScope:pack?.chart_scope}} active={view==='Chart'&&table?.id===t.id}/>
      </div>}
    </div>)}
    {!table && artifacts.length>0 && <><p>Captured exports alone do not establish calculation completion.</p><ChartArtifact artifacts={artifacts} active={view==='Chart'}/></>}
    {table && artifacts.length>0 && <details><summary>Python exports — not used as calculation evidence</summary><p>The verified chart view is generated from the calculation tables. These original exports have not been validated against all table values.</p>{artifacts.map(a=>a.download_url?.startsWith('/projects/') && !a.download_url.includes('..') ? <p key={a.id}><a className="btn btn-secondary" href={(import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000/api/v1')+a.download_url} download>Download original {a.kind} export</a></p> : null)}</details>}
    <CalculationDetails calculation={pack?.provenance || snapshot.calculation}/>
  </section>;
}
