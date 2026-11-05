import { useEffect, useState } from "react";
import { ArrowUpRight, Search, Library } from "lucide-react";
import { useProject } from "../../context/ProjectContext";

function titleFor(snapshot) {
  if (snapshot.question) return snapshot.question;
  const text = (snapshot.content || "").replace(/[#*`]/g, "").split("\n").find(line => line.trim());
  return text?.trim() || `Analysis of ${(snapshot.result?.columns || []).join(" and ")}`;
}
function sourceFor(snapshot) {
  return (snapshot.tables || []).map(table => table.replace("::", " / ")).join(" + ") || "Source unavailable";
}

export default function SavedAnalyses({ onOpenResult }) {
  const { activeProjectId, activeProjectName, loadSavedAnalyses } = useProject();
  const [state, setState] = useState(null);
  const [query, setQuery] = useState("");
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
  const current = state?.projectId === activeProjectId ? state : null;
  const available = (current?.snapshots || []).filter(item => !item.unavailable);
  const unavailable = (current?.snapshots || []).length - available.length;
  const needle = query.trim().toLowerCase();
  const matches = available.filter(item => `${titleFor(item)} ${sourceFor(item)} ${item.result.columns.join(" ")}`.toLowerCase().includes(needle));
  return <section className="analysis-library" aria-label="Saved analysis library">
    <div className="library-intro">
      <div><p>Results saved automatically from your analyst conversations.</p></div>
      <span className="library-project">{activeProjectName}</span>
    </div>
    {!activeProjectId ? <p>Select a project to see its analyses.</p> : !current ? <p role="status">Loading saved analyses…</p> : current.error ?
      <div role="alert"><p>Saved analyses couldn’t be loaded.</p><button className="btn btn-secondary" onClick={() => setAttempt(value => value + 1)}>Try again</button></div> : <>
      <div className="library-search"><Search size={17} aria-hidden="true" /><input className="input-text" type="search" aria-label="Search saved analyses" placeholder="Search questions, summaries, or tables" value={query} onChange={event => setQuery(event.target.value)} /></div>
      <p className="library-count">{needle ? `${matches.length} matching analyses` : `${available.length} saved analyses · newest first`}</p>
      {matches.length ? <ul className="analysis-list">{matches.map((snapshot) => <li key={snapshot.id}>
        <button className="analysis-entry" onClick={() => onOpenResult({ ...snapshot, fromLibrary: true })}>
          <span className="analysis-icon"><Library size={18} /></span>
          <span className="analysis-copy"><span className="analysis-kind">{snapshot.question ? "Original question" : "Saved summary"}</span><span className="analysis-title">{titleFor(snapshot)}</span><span className="analysis-saved">{snapshot.saved_at ? <time dateTime={snapshot.saved_at}>{new Date(snapshot.saved_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}</time> : "Save time unavailable"}</span><span className="analysis-source">{sourceFor(snapshot)}</span><span className="analysis-meta">{snapshot.result.data.length.toLocaleString()} rows · {snapshot.result.columns.length} columns<span className="analysis-fields"> · {snapshot.result.columns.join(" · ")}</span></span></span>
          <span className="analysis-open">Open result <ArrowUpRight size={16} /></span>
        </button>
      </li>)}</ul> : <div className="workspace-empty"><Library size={28} /><h2>{needle ? "No matching analyses" : "Your insights will appear here"}</h2><p>{needle ? "Try a table name or clear your search." : "Ask the analyst a question that produces a table. Its result will be available here after it finishes."}</p></div>}
      {unavailable > 0 && <details className="library-unavailable"><summary>{unavailable} older {unavailable === 1 ? "result is" : "results are"} unavailable</summary><p>These saved results are too large to open in this workspace. Ask the analyst for a smaller summary if you need them again.</p></details>}
    </>}
  </section>;
}
