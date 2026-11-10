import { Table2, ChartBar, CircleCheck, TriangleAlert, CircleX } from "lucide-react";
import { useState } from "react";
import CalculationDetails from "../chat/CalculationDetails";
import ResultTable from "../chat/ResultTable";
import ChartArtifact from "./ChartArtifact";
import ResultChart from "./ResultChart";
import { calculationOutputs, chartsForOutput, chartControlsAvailable } from "./analysisPackage";

function OutputCharts({ table, snapshot, charts, active }) {
  const choices=chartsForOutput({charts},table.id);
  const [chosen,setChosen]=useState(choices[0]?.id);
  const [visited,setVisited]=useState([choices[0]?.id]);
  const current=choices.find(c=>c.id===chosen) || choices[0];
  return <>
    {choices.length>1 && <label className="result-output-picker">Chart<select className="input-text" value={current.id} onChange={e=>{setChosen(e.target.value);setVisited(previous=>previous.includes(e.target.value)?previous:[...previous,e.target.value]);}}>{choices.map((c,i)=><option key={c.id} value={c.id}>{c.specification?.title || `Chart ${i+1}`}</option>)}</select></label>}
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
  const chartsAllowed=chartControlsAvailable(pack);
  const activeView=chartsAllowed?view:'Table';
  const charts=pack?.charts?.filter(c=>c.kind==='result') || [];
  const comparison=table?.result.comparison_audit;
  const entity=table?.result.entity_audit;
  return <section className="result-workspace" aria-label="Analysis result">
    {snapshot.question && <p className="result-question"><strong>Question</strong> {snapshot.question}</p>}
    {pack && <p role="status" className="result-status" data-status={pack.status}>
      {pack.status === 'complete' ? <CircleCheck size={14} aria-hidden="true" /> : pack.status === 'failed' ? <CircleX size={14} aria-hidden="true" /> : <TriangleAlert size={14} aria-hidden="true" />}
      Analysis {pack.status.replaceAll('_', ' ')}
    </p>}
    {tables.length>1 && <label className="result-output-picker">Calculation output<select className="input-text" value={table?.id} onChange={e=>{setSelected(e.target.value);if(view==='Chart')setOpened(previous=>previous.includes(e.target.value)?previous:[...previous,e.target.value]);}}>{tables.map(t=><option key={t.id} value={t.id}>{t.label}{t.completion_status === "incomplete" ? " (incomplete)" : ""}</option>)}</select></label>}
    <div className="workspace-toolbar result-toolbar" role="group" aria-label="Result view">
      {(table?(chartsAllowed?['Table','Chart']:['Table']):(chartsAllowed?['Chart']:[])).map(label=><button key={label} type="button" className={`btn ${activeView===label?'btn-primary':'btn-secondary'}`} aria-pressed={activeView===label} onClick={()=>{setView(label);if(label==='Chart'&&table)setOpened(previous=>previous.includes(table.id)?previous:[...previous,table.id]);}}>
        {label==='Table'?<Table2 size={14}/>:<ChartBar size={14}/>} {label}
      </button>)}
      <span className="result-dimensions">{table?`${table.result.data.length.toLocaleString()} rows / ${table.result.columns.length} columns`:`${artifacts.length} captured exports`}</span>
    </div>
    <p className="result-source">Source: {table?.source?.tables?.join(' · ') || snapshot.tables?.join(' · ') || 'Unavailable'}{table?.result.source_observation_count!=null?` · ${table.result.source_observation_count.toLocaleString()} source observations`:''}</p>
    {tables.map(t=><div className="result-output" key={t.id} hidden={table?.id!==t.id}>
      <div hidden={activeView!=='Table'}><ResultTable result={t.result}/></div>
      {chartsAllowed && opened.includes(t.id) && <div hidden={view!=='Chart'}>
        <OutputCharts table={t} charts={charts} snapshot={{...snapshot,chartScope:pack?.chart_scope}} active={view==='Chart'&&table?.id===t.id}/>
      </div>}
    </div>)}
    {chartsAllowed && !table && artifacts.length>0 && <><p>Captured exports alone do not establish calculation completion.</p><ChartArtifact artifacts={artifacts} active={view==='Chart'}/></>}
    {table && artifacts.length>0 && <details><summary>Python exports — not used as calculation evidence</summary><p>The verified chart view is generated from the calculation tables. These original exports have not been validated against all table values.</p>{artifacts.map(a=>a.download_url?.startsWith('/projects/') && !a.download_url.includes('..') ? <p key={a.id}><a className="btn btn-secondary" href={(import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000/api/v1')+a.download_url} download>Download original {a.kind} export</a></p> : null)}</details>}
    {(pack || comparison) && <details className="result-validation">
      <summary>Definition and verification details</summary>
      {pack && (pack.status === 'complete' ? <p>Declared calculation requirements completed.</p> : <ul>{(pack.incomplete_reasons || []).map((reason, i) => <li key={i}>{reason}</li>)}</ul>)}
      {comparison && <>
        <p>Comparison: {comparison.parameters.column} {comparison.parameters.operator} {comparison.parameters.value_column}{comparison.parameters.date_part === 'date' ? ' using calendar dates' : ''}. Equality {['>=','<=','=='].includes(comparison.parameters.operator) ? 'matches' : 'does not match'} this condition.</p>
        <p>Percentage = 100 × matched count / comparable count. Both values must be present in the eligibility-filtered population. Missing actual values are counted across that population; missing comparison values are counted only among observations with an actual value. A zero denominator is undefined.</p>
        <p>Eligible population: {comparison.filtered_count.toLocaleString()} · Comparable: {comparison.comparable_count.toLocaleString()} · Matched: {comparison.matched_count.toLocaleString()}.</p>
        {table.result.result_scope && <p>The table retains every group. Undefined percentages sort last. Chart Top N changes the chart only.</p>}
      </>}
      {entity && <>
        <p>Measurements are averaged within each {entity.entity_key} first, then contributing entities are averaged with equal weight. The join retains one row per selected entity.</p>
        <p>Population: {entity.population_count.toLocaleString()} · Comparable: {entity.comparable_count.toLocaleString()} · Contributing: {entity.contributing_count.toLocaleString()}.</p>
        <p>Missing actual values: {entity.missing_actual_count.toLocaleString()}. Missing comparison values among entities with actual values: {entity.missing_comparison_count.toLocaleString()}.</p>
        <p>Among comparable entities, {entity.missing_record_count.toLocaleString()} have no measurement records and {entity.unusable_measurement_count.toLocaleString()} have records with no usable measurement. These exclusions are separate from missing dates. Empty means remain undefined.</p>
        <details><summary>Full staged calculation audit</summary><pre>{JSON.stringify(entity,null,2)}</pre></details>
      </>}
      {pack?.completion_checks?.length > 0 && <ul>{pack.completion_checks.map((check,i) => <li key={i}>{check.requirement_id}: {check.status}</li>)}</ul>}
    </details>}
    <CalculationDetails calculation={pack?.provenance || snapshot.calculation} analysisPackage={pack}/>
  </section>;
}
