export default function CalculationDetails({ calculation }) {
  if (!calculation?.steps?.length) return null;
  return (
    <details className="calculation-details">
      <summary>How this was calculated</summary>
      <ol>
        {calculation.steps.map((step, stepIndex) => (
          <li key={stepIndex}>
            <strong>{step.tool.replaceAll("_", " ")}</strong>
            {" · "}{step.status}
            {step.execution_skipped && <p>Not executed: this repeats an earlier failed call.</p>}
            {step.tables?.length > 0 && <p>Data used: {step.tables.join(", ")}</p>}
            {step.join_keys?.length > 0 && (
              <ul>
                {step.join_keys.map((key, keyIndex) => (
                  <li key={keyIndex}>
                    {key.from_table}.{key.from_column} = {key.to_table}.{key.to_column}
                  </li>
                ))}
              </ul>
            )}
            {step.parameters && (
              <pre>{step.parameters.code ?? JSON.stringify(step.parameters, null, 2)}</pre>
            )}
            {step.error && <p>{step.error}</p>}
          </li>
        ))}
      </ol>
    </details>
  );
}
