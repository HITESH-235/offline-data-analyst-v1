import { useEffect, useState } from "react";
import { ArrowUpRight, Search, Library, Trash2 } from "lucide-react";
import { useProject } from "../../context/ProjectContext";

function titleFor(snapshot) {
  if (snapshot.unavailable) return "Older unavailable analysis";
  if (snapshot.question) return snapshot.question;
  const text = (snapshot.content || "").replace(/[#*`]/g, "").split("\n").find(line => line.trim());
  return text?.trim() || `Analysis of ${(snapshot.result?.columns || []).join(" and ")}`;
}
function sourceFor(snapshot) {
  return (snapshot.tables || []).map(table => table.replace("::", " / ")).join(" + ") || "Source unavailable";
}

export default function SavedAnalyses({ onOpenResult }) {
  const { activeProjectId, activeProjectName, loadSavedAnalyses, deleteSavedAnalysis } = useProject();
  const [state, setState] = useState(null);
  const [query, setQuery] = useState("");
  const [deleting, setDeleting] = useState(null);
  const [deleteError, setDeleteError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setState(null);
    setQuery("");
    if (activeProjectId) loadSavedAnalyses(activeProjectId, controller.signal).then(snapshots => {
      if (!controller.signal.aborted) setState({ projectId: activeProjectId, snapshots });
    }).catch(error => {
      if (!controller.signal.aborted) setState({ projectId: activeProjectId, error: error.message });
    });
    return () => controller.abort();
  }, [activeProjectId, loadSavedAnalyses, attempt]);
  const remove = async snapshot => {
    if (!window.confirm(`Delete this saved analysis?\n\n${titleFor(snapshot)}\n\nThis permanently removes its saved result and generated chart files. Conversation text and datasets stay available.`)) return;
    const projectId = activeProjectId;
    setDeleting(snapshot.id); setDeleteError('');
    try {
      await deleteSavedAnalysis(projectId, snapshot.id);
      setState(previous => previous?.projectId === projectId ? { ...previous, snapshots: previous.snapshots.filter(item => item.id !== snapshot.id) } : previous);
    } catch (error) { setDeleteError(error.message); }
    finally { setDeleting(null); }
  };
  const current = state?.projectId === activeProjectId ? state : null;
  const available = (current?.snapshots || []).filter(item => !item.unavailable);
  const unavailable = (current?.snapshots || []).length - available.length;
  const needle = query.trim().toLowerCase();
  const matches = available.filter(item => `${titleFor(item)} ${sourceFor(item)} ${(item.result?.columns || []).join(" ")}`.toLowerCase().includes(needle));
  return <section className="analysis-library" aria-label="Saved analysis library">
    <div className="library-intro">
      <div><p>Results saved automatically from your analyst conversations.</p></div>
      <span className="library-project">{activeProjectName}</span>
    </div>
    {!activeProjectId ? <p>Select a project to see its analyses.</p> : !current ? <p role="status">Loading saved analyses…</p> : current.error ?
      <div role="alert"><p>Saved analyses couldn’t be loaded.</p><button className="btn btn-secondary" onClick={() => setAttempt(value => value + 1)}>Try again</button></div> : <>
      <div className="library-search"><Search size={17} aria-hidden="true" /><input className="input-text" type="search" aria-label="Search saved analyses" placeholder="Search questions, summaries, or tables" value={query} onChange={event => setQuery(event.target.value)} /></div>
      {deleteError && <p role="alert">{deleteError}</p>}
      <p className="library-count">{needle ? `${matches.length} matching analyses` : `${available.length} saved analyses · newest first`}</p>
      {matches.length ? <ul className="analysis-list">{matches.map((snapshot) => <li key={snapshot.id} className="analysis-list-row">
        <button className="analysis-entry" onClick={() => onOpenResult({ ...snapshot, fromLibrary: true })}>
          <span className="analysis-icon"><Library size={18} /></span>
          <span className="analysis-copy"><span className="analysis-kind">{snapshot.question ? "Original question" : "Saved summary"}</span><span className="analysis-title">{titleFor(snapshot)}</span><span className="analysis-saved">{snapshot.saved_at ? <time dateTime={snapshot.saved_at}>{new Date(snapshot.saved_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}</time> : "Save time unavailable"}</span><span className="analysis-source">{sourceFor(snapshot)}</span><span className="analysis-meta">{snapshot.result?.data ? `${snapshot.result.data.length.toLocaleString()} rows · ${snapshot.result.columns.length} columns` : `${snapshot.artifacts?.length || 0} generated charts`}<span className="analysis-fields">{snapshot.artifacts?.length ? ` · ${snapshot.artifacts.map(artifact => artifact.kind === "png" ? "PNG image" : "Plotly chart").join(", ")}` : ""}</span></span></span>
          <span className="analysis-open">Open result <ArrowUpRight size={16} /></span>
        </button>
        <button type="button" className="btn analysis-delete" aria-label={`Delete saved analysis: ${titleFor(snapshot)}`} disabled={deleting !== null} onClick={() => remove(snapshot)}><Trash2 size={15} />{deleting === snapshot.id ? "Deleting…" : "Delete"}</button>
      </li>)}</ul> : <div className="workspace-empty"><Library size={28} /><h2>{needle ? "No matching analyses" : "Your insights will appear here"}</h2><p>{needle ? "Try a table name or clear your search." : "Ask the analyst a question that produces a table. Its result will be available here after it finishes."}</p></div>}
      {unavailable > 0 && <details className="library-unavailable"><summary>{unavailable} older {unavailable === 1 ? "result is" : "results are"} unavailable</summary><p>These saved results are too large to open in this workspace. Ask the analyst for a smaller summary if you need them again.</p>{current.snapshots.filter(item => item.unavailable).map(item => <div key={item.id}><button className="btn analysis-delete-unavailable" disabled={deleting !== null} onClick={() => remove(item)}><Trash2 size={14} />Delete unavailable saved result</button></div>)}</details>}
    </>}
  </section>;
}
