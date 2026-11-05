import { Table2, ChartBar } from "lucide-react";
import { useState } from "react";
import CalculationDetails from "../chat/CalculationDetails";
import ResultTable from "../chat/ResultTable";
import ResultChart from "./ResultChart";

export default function ResultWorkspace({ snapshot }) {
  const [view, setView] = useState("Table");
  const [chartOpened, setChartOpened] = useState(false);

  return (
    <section className="result-workspace" aria-label="Analysis result">
      <div className="workspace-toolbar result-toolbar" role="group" aria-label="Result view">
        {["Table", "Chart"].map((label) => (
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
        <span className="result-dimensions">{snapshot.result.data.length.toLocaleString()} rows <span aria-hidden="true"> / </span> {snapshot.result.columns.length} columns</span>
      </div>
      <div hidden={view !== "Table"}>
        <ResultTable result={snapshot.result} />
      </div>
      {chartOpened && (
        <div hidden={view !== "Chart"}>
          <ResultChart result={snapshot.result} />
        </div>
      )}
      <CalculationDetails calculation={snapshot.calculation} />
    </section>
  );
}
