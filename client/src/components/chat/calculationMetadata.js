function expression(node) {
  if (!node) return '';
  if ('column' in node) return node.column;
  if ('value' in node) return String(node.value);
  const op = { multiply: ' × ', subtract: ' − ', add: ' + ' }[node.op];
  return op ? `(${(node.args || []).map(expression).join(op)})` : JSON.stringify(node);
}
const predicate = f => `${f.column} ${f.operator} ${f.value_column ?? JSON.stringify(f.value)}${f.date_part === 'date' ? ' (calendar date)' : ''}`;

export function calculationDetailSteps(calculation, pack) {
  const tables = pack?.tables || [];
  const saved = pack?.provenance?.steps?.length ? pack.provenance.steps : calculation?.steps || [];
  const steps = saved.length ? saved : tables.map(t => ({ output_id: t.id, tool: t.tool || t.result?.analysis_kind || 'calculation', parameters: t.parameters, tables: t.source?.tables, join_keys: t.source?.join_keys, status: t.completion_status || 'saved' }));
  return steps.map((step, index) => {
    const table = tables.find(t => t.id === step.output_id) || tables.find(t => t.step_index === index);
    const p = step.parameters || table?.parameters || {};
    const formulas = [];
    for (const m of p.measures || []) formulas.push(`${m.label}: ${m.operation}(${m.column})${m.divide_by != null ? ` / ${m.divide_by}` : ''}${m.unit ? ` [${m.unit}]` : ''}`);
    if (p.statistics) formulas.push(`Statistics: ${p.statistics.join(', ')} for ${(p.columns || []).join(', ')}${p.unit ? ` [${p.unit}]` : ''}; count is nonmissing count.`);
    if (p.aggregations) for (const [column, op] of Object.entries(p.aggregations)) formulas.push(`${op}(${column})`);
    if (p.date_column && p.years?.length) formulas.push(`Calendar scope: ${p.years.join(', ')}, by ${p.grain}, using ${p.date_column}.`);
    if (p.group_by?.length) formulas.push(`Grouped by ${p.group_by.join(', ')}.`);
    if (p.metric) formulas.push(`${p.metric.name}: ${p.metric.aggregation}(${expression(p.metric.expression) || 'rows'})${p.metric.unit ? ` [${p.metric.unit}]` : ''}`);
    if (p.comparison || p.value_column) formulas.push(predicate(p.comparison || p));
    if (p.measurement) formulas.push(`${p.measurement.name}: mean(${expression(p.measurement.expression)}) within ${p.entity_key}, then mean of contributing entity means with equal entity weight.`);
    const audit = table?.result?.entity_audit || table?.result?.comparison_audit;
    const exclusions = [];
    if (audit) {
      exclusions.push(`Missing actual values: ${audit.missing_actual_count ?? 0}. Missing comparison values among entities with an actual value: ${audit.missing_comparison_count ?? 0}.`);
      if (audit.exclusion_definition) exclusions.push(audit.exclusion_definition);
      else exclusions.push('Missing either comparison value excludes the observation from the comparable denominator.');
      if (table.result.entity_audit) exclusions.push(`Among comparable entities: ${audit.missing_record_count} have no measurement records; ${audit.unusable_measurement_count} have records without usable measurements.`);
    }
    return { ...step, sources: step.tables?.length ? step.tables : table?.source?.tables || [], join_keys: step.join_keys?.length ? step.join_keys : table?.source?.join_keys || [], filters: (p.filters || p.eligibility_filters || []).map(predicate), formulas, exclusions };
  });
}
