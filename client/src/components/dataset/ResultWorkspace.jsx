import { Table2, ChartBar } from "lucide-react";
import { useState } from "react";
import CalculationDetails from "../chat/CalculationDetails";
import ResultTable from "../chat/ResultTable";
import ChartArtifact from "./ChartArtifact";
import ResultChart from "./ResultChart";

export default function ResultWorkspace({ snapshot }) {
  const hasTable = Array.isArray(snapshot.result?.data) && snapshot.result?.columns?.length > 0;
  const artifacts = snapshot.artifacts || [];
  const [view, setView] = useState(hasTable ? "Table" : "Chart");
  const [chartOpened, setChartOpened] = useState(!hasTable);

  return (
    <section className="result-workspace" aria-label="Analysis result">
      {snapshot.question && <p className="result-question"><strong>Question</strong> {snapshot.question}</p>}
      <div className="workspace-toolbar result-toolbar" role="group" aria-label="Result view">
        {(hasTable ? ["Table", "Chart"] : ["Chart"]).map((label) => (
          <button
            key={label}
            type="button"
            className={`btn ${view === label ? "btn-primary" : "btn-secondary"}`}
            aria-pressed={view === label}
            onClick={() => {
              setView(label);
              if (label === "Chart") setChartOpened(true);
            }}
          >
            {label === "Table" ? <Table2 size={14} /> : <ChartBar size={14} />}
            {label}
          </button>
        ))}
        <span className="result-dimensions">{hasTable ? `${snapshot.result.data.length.toLocaleString()} rows / ${snapshot.result.columns.length} columns` : `${artifacts.length} generated chart${artifacts.length === 1 ? "" : "s"}`}</span>
      </div>
      {hasTable && <div hidden={view !== "Table"}>
        <ResultTable result={snapshot.result} />
      </div>}
      {chartOpened && (
        <div hidden={view !== "Chart"}>
          {artifacts.length ? <ChartArtifact artifacts={artifacts} active={view === "Chart"} /> : hasTable ? <ResultChart result={snapshot.result} snapshot={snapshot} active={view === "Chart"} /> : <p>No chart output was captured.</p>}
        </div>
      )}
      <CalculationDetails calculation={snapshot.calculation} />
    </section>
  );
}
