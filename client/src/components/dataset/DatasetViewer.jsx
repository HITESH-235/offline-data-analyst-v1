import React, { useState } from "react";
import { useProject } from "../../context/ProjectContext";
import { Table, BarChart2, Hash, AlertTriangle, Disc } from "lucide-react";

export const DatasetViewer = () => {
  const { activeDatasetPreview, activeDatasetProfile, isLoading } = useProject();
  const [activeTab, setActiveTab] = useState("preview"); // "preview" or "profile"

  if (isLoading) {
    return (
      <div style={{ display: "flex", flex: 1, alignItems: "center", justifyContent: "center", height: "100%" }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "10px" }}>
          <div className="spinner"></div>
          <span style={{ fontSize: "14px", color: "var(--text-secondary)" }}>Loading dataset parameters...</span>
        </div>
      </div>
    );
  }

  if (!activeDatasetPreview) {
    return (
      <div style={{ display: "flex", flex: 1, alignItems: "center", justifyContent: "center", height: "100%", color: "var(--text-muted)", fontSize: "14px" }}>
        No dataset selected. Please choose a dataset from the available datasets catalog in the sidebar.
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "16px", height: "100%" }}>
      {/* Tabs head bar */}
      <div style={{ display: "flex", gap: "12px", borderBottom: "1px solid var(--border-color)", paddingBottom: "8px" }}>
        <button
          className={`btn ${activeTab === "preview" ? "btn-primary" : "btn-secondary"}`}
          onClick={() => setActiveTab("preview")}
          style={{ padding: "6px 12px", fontSize: "13px" }}
        >
          <Table size={14} />
          <span>Data Preview</span>
        </button>
        <button
          className={`btn ${activeTab === "profile" ? "btn-primary" : "btn-secondary"}`}
          onClick={() => setActiveTab("profile")}
          style={{ padding: "6px 12px", fontSize: "13px" }}
        >
          <BarChart2 size={14} />
          <span>Data Profiling</span>
        </button>
      </div>

      {/* Tab body content */}
      <div style={{ flex: 1, minHeight: 0, overflowY: "auto" }}>
        {activeTab === "preview" ? (
          <div className="table-container" style={{ maxHeight: "100%" }}>
            <table className="data-table">
              <thead>
                <tr>
                  {activeDatasetPreview.columns.map((col, idx) => (
                    <th key={idx}>{col}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {activeDatasetPreview.data.map((row, rowIdx) => (
                  <tr key={rowIdx}>
                    {activeDatasetPreview.columns.map((col, colIdx) => (
                      <td key={colIdx} title={String(row[col])}>
                        {String(row[col])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
            {/* Total Row summaries */}
            {activeDatasetProfile && (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "12px" }}>
                <div className="glass-panel" style={{ padding: "16px", display: "flex", flexDirection: "column" }}>
                  <span style={{ fontSize: "12px", color: "var(--text-muted)" }}>Total Row Count</span>
                  <span style={{ fontSize: "24px", fontWeight: "700", fontFamily: "var(--font-title)" }}>
                    {activeDatasetProfile.row_count.toLocaleString()}
                  </span>
                </div>
                <div className="glass-panel" style={{ padding: "16px", display: "flex", flexDirection: "column" }}>
                  <span style={{ fontSize: "12px", color: "var(--text-muted)" }}>Columns Count</span>
                  <span style={{ fontSize: "24px", fontWeight: "700", fontFamily: "var(--font-title)" }}>
                    {activeDatasetProfile.columns.length}
                  </span>
                </div>
                <div className="glass-panel" style={{ padding: "16px", display: "flex", flexDirection: "column" }}>
                  <span style={{ fontSize: "12px", color: "var(--text-muted)" }}>Generated at</span>
                  <span style={{ fontSize: "13px", fontWeight: "500", marginTop: "12px", textOverflow: "ellipsis", overflow: "hidden", whiteSpace: "nowrap" }}>
                    {new Date(activeDatasetProfile.generated_at).toLocaleString()}
                  </span>
                </div>
              </div>
            )}

            {/* Columns Profiles Breakdown */}
            <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
              <h4 style={{ fontSize: "14px", fontWeight: "600", color: "var(--text-secondary)" }}>Columns Statistics</h4>
              {activeDatasetProfile && activeDatasetProfile.columns.map((col, idx) => {
                const dtype = activeDatasetProfile.data_types[col] || "unknown";
                const isNumeric = activeDatasetProfile.numeric_summary[col] !== undefined;
                const missing = activeDatasetProfile.missing_values[col] || 0;
                const uniques = activeDatasetProfile.unique_values[col] || 0;
                
                return (
                  <div key={idx} className="glass-panel" style={{ padding: "14px", display: "flex", flexDirection: "column", gap: "8px" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                        <span style={{ fontWeight: "600", fontSize: "14px" }}>{col}</span>
                        <span style={{ fontSize: "11px", color: "var(--accent-color)", background: "var(--accent-glow)", padding: "2px 6px", borderRadius: "4px", fontFamily: "var(--font-mono)" }}>
                          {dtype}
                        </span>
                      </div>
                      <div style={{ display: "flex", gap: "12px", fontSize: "12px", color: "var(--text-secondary)" }}>
                        <span style={{ display: "flex", alignItems: "center", gap: "4px" }}>
                          <Hash size={12} /> Uniques: {uniques}
                        </span>
                        <span style={{ display: "flex", alignItems: "center", gap: "4px", color: missing > 0 ? "var(--warning-color)" : "var(--text-secondary)" }}>
                          <AlertTriangle size={12} /> Missing: {missing}
                        </span>
                      </div>
                    </div>

                    {isNumeric ? (
                      <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: "8px", background: "rgba(255,255,255,0.02)", padding: "8px", borderRadius: "6px", fontSize: "12px" }}>
                        <div><span style={{ color: "var(--text-muted)" }}>Mean:</span> {activeDatasetProfile.numeric_summary[col].mean.toFixed(2)}</div>
                        <div><span style={{ color: "var(--text-muted)" }}>Std:</span> {activeDatasetProfile.numeric_summary[col].std.toFixed(2)}</div>
                        <div><span style={{ color: "var(--text-muted)" }}>Min:</span> {activeDatasetProfile.numeric_summary[col].min}</div>
                        <div><span style={{ color: "var(--text-muted)" }}>Max:</span> {activeDatasetProfile.numeric_summary[col].max}</div>
                        <div><span style={{ color: "var(--text-muted)" }}>Median:</span> {activeDatasetProfile.numeric_summary[col]["50%"]}</div>
                      </div>
                    ) : (
                      activeDatasetProfile.categorical_summary[col] && (
                        <div style={{ display: "flex", gap: "16px", background: "rgba(255,255,255,0.02)", padding: "8px", borderRadius: "6px", fontSize: "12px" }}>
                          <div><span style={{ color: "var(--text-muted)" }}>Top Value:</span> "{activeDatasetProfile.categorical_summary[col].top}"</div>
                          <div><span style={{ color: "var(--text-muted)" }}>Freq:</span> {activeDatasetProfile.categorical_summary[col].frequency}</div>
                        </div>
                      )
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
export default DatasetViewer;
