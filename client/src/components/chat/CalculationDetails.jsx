import { calculationDetailSteps } from "./calculationMetadata";

export default function CalculationDetails({ calculation, analysisPackage }) {
  const steps = calculationDetailSteps(calculation, analysisPackage);
  if (!steps.length) return null;
  return (
    <details className="calculation-details">
      <summary>How this was calculated</summary>
      <ol>
        {steps.map((step, stepIndex) => (
          <li key={stepIndex}>
            <strong>{step.tool.replaceAll("_", " ")}</strong>
            {" · "}{step.status}
            {step.superseded && <p>Superseded by a later calculation; its charts are not final results.</p>}
            {step.execution_skipped && <p>Not executed: this repeats an earlier failed call.</p>}
            {step.sources?.length > 0 && <p>Data used: {step.sources.join(", ")}</p>}
            {step.join_keys?.length > 0 && (
              <ul>
                {step.join_keys.map((key, keyIndex) => (
                  <li key={keyIndex}>
                    {key.from_table}.{key.from_column} = {key.to_table}.{key.to_column}
                  </li>
                ))}
              </ul>
            )}
            {step.filters.length > 0 && <p>Filters: {step.filters.join("; ")}</p>}
            {step.formulas.map((formula, i) => <p key={`formula-${i}`}>{formula}</p>)}
            {step.exclusions.map((note, i) => <p key={`exclusion-${i}`}>{note}</p>)}
            {step.parameters && (
              <details><summary>Full calculation metadata</summary><pre>{step.parameters.code ?? JSON.stringify(step.parameters, null, 2)}</pre></details>
            )}
            {step.error && <p>{step.error}</p>}
          </li>
        ))}
      </ol>
    </details>
  );
}
