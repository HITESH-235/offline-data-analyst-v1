// The package is authoritative when present. Legacy snapshots remain readable.
export function calculationOutputs(snapshot) {
  if (snapshot.analysisPackage) return snapshot.analysisPackage.tables || [];
  return snapshot.result?.columns?.length
    ? [{ id: 'legacy', label: 'Result', result: snapshot.result }]
    : [];
}

export function calculationSources(pack, fallback = []) {
  if (!pack?.tables?.length) return fallback;
  return [...new Set(pack.tables.flatMap(table => table.source?.tables || []))];
}

export function chartsForOutput(pack, outputId) {
  if (!chartControlsAvailable(pack)) return [];
  return (pack?.charts || []).filter(chart => chart.kind === 'result' && chart.table_id === outputId);
}

export function chartPreference(pack) {
  const scope = pack?.chart_scope || {};
  return scope.preference || (scope.required ? 'required' : 'automatic');
}
export function chartControlsAvailable(pack) { return chartPreference(pack) !== 'disabled'; }
