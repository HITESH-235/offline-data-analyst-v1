import { chartPreference } from "../dataset/analysisPackage.js";
// Historical packages have no saved presentation flags. Adapt them read-only.
export function chatPresentation(pack, result, step, artifacts = [], scalarAnswer = false) {
  if (pack?.presentation) return { hasDetail: Boolean(pack.presentation.has_detail || artifacts.length) };
  const tables = pack?.tables || (result?.columns?.length ? [{ result, parameters: step?.parameters || {}, tool: step?.tool }] : []);
  const compact = tables.length > 0 && tables.every(t => (t.result.analysis_kind || t.tool) === 'aggregation'
    && !t.parameters?.group_by?.length && t.result.data?.length === 1 && t.result.columns?.length
    && Object.values(t.result.data[0]).every(v => v == null || ['string', 'number', 'boolean'].includes(typeof v)))
    && tables.reduce((n, t) => n + t.result.columns.length, 0) <= 6;
  const tableRequested = Boolean(pack?.presentation?.table_requested);
  const usefulCharts = chartPreference(pack) !== 'disabled' && (pack?.charts || []).some(c => c.kind === 'artifact' || !compact || chartPreference(pack) === 'required');
  return { hasDetail: Boolean(artifacts.length || usefulCharts || (tables.length && (tableRequested || (!compact && !scalarAnswer)))) };
}

export function chatContent(content, hasDetail) {
  return hasDetail ? content : (content || '').replace(/The full breakdown is available in (?:\*\*)?Open result(?:\*\*)?\./g, '').trim();
}
