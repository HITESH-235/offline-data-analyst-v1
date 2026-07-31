import React, { useState } from "react";
import { useProject } from "../../context/ProjectContext";
import {
  Folder,
  Plus,
  Trash2,
  Edit3,
  FileSpreadsheet,
  Database,
  ChevronDown,
  ChevronRight,
  Table as TableIcon,
} from "lucide-react";

export const Sidebar = () => {
  const {
    projects,
    activeProjectId,
    datasets,
    activeDatasetId,
    createProject,
    renameProject,
    deleteProject,
    selectProject,
    selectDataset,
  } = useProject();

  const [newProjectName, setNewProjectName] = useState("");
  const [isCreating, setIsCreating] = useState(false);
  const [collapsedDbs, setCollapsedDbs] = useState({});

  const toggleDbCollapse = (dbName) => {
    setCollapsedDbs((prev) => ({
      ...prev,
      [dbName]: !prev[dbName],
    }));
  };

  const handleCreate = async (e) => {
    e.preventDefault();
    if (!newProjectName.trim()) return;
    await createProject(newProjectName.trim());
    setNewProjectName("");
    setIsCreating(false);
  };

  const handleRename = (id, currentName) => {
    const newName = prompt("Enter new project name:", currentName);
    if (newName && newName.trim() && newName !== currentName) {
      renameProject(id, newName.trim());
    }
  };

  // Organize datasets into standalone files and database groups
  const standaloneDatasets = [];
  const dbGroups = {};

  datasets.forEach((ds) => {
    if (ds.parent_db) {
      if (!dbGroups[ds.parent_db]) {
        dbGroups[ds.parent_db] = [];
      }
      dbGroups[ds.parent_db].push(ds);
    } else {
      standaloneDatasets.push(ds);
    }
  });

  return (
    <aside className="left-panel">
      {/* Project Switcher section */}
      <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h3 style={{ fontSize: "14px", fontWeight: "600", textTransform: "uppercase", color: "var(--text-secondary)" }}>
            Projects
          </h3>
          <button className="btn btn-secondary" style={{ padding: "4px 8px" }} onClick={() => setIsCreating(!isCreating)}>
            <Plus size={16} />
          </button>
        </div>

        {isCreating && (
          <form onSubmit={handleCreate} style={{ display: "flex", gap: "6px" }}>
            <input
              type="text"
              className="input-text"
              placeholder="Project name..."
              value={newProjectName}
              onChange={(e) => setNewProjectName(e.target.value)}
              autoFocus
            />
            <button className="btn btn-primary" style={{ padding: "8px" }} type="submit">
              Go
            </button>
          </form>
        )}

        <div style={{ display: "flex", flexDirection: "column", gap: "4px", maxHeight: "180px", overflowY: "auto" }}>
          {projects.map((proj) => (
            <div
              key={proj.id}
              className="glass-panel"
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                padding: "8px 12px",
                cursor: "pointer",
                borderRadius: "8px",
                background: activeProjectId === proj.id ? "rgba(99, 102, 241, 0.15)" : "var(--bg-card)",
                borderColor: activeProjectId === proj.id ? "var(--accent-color)" : "var(--border-color)",
              }}
              onClick={() => selectProject(proj.id, proj.name)}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "8px", minWidth: 0 }}>
                <Folder size={16} color={activeProjectId === proj.id ? "#818cf8" : "#9ca3af"} />
                <span style={{ fontSize: "13px", fontWeight: "500", textOverflow: "ellipsis", overflow: "hidden", whiteSpace: "nowrap" }}>
                  {proj.name}
                </span>
              </div>
              <div style={{ display: "flex", gap: "4px" }} onClick={(e) => e.stopPropagation()}>
                <button
                  style={{ background: "transparent", border: "none", color: "var(--text-secondary)", cursor: "pointer" }}
                  onClick={() => handleRename(proj.id, proj.name)}
                >
                  <Edit3 size={14} />
                </button>
                <button
                  style={{ background: "transparent", border: "none", color: "var(--danger-color)", cursor: "pointer" }}
                  onClick={() => {
                    if (confirm(`Are you sure you want to delete project "${proj.name}"? This removes all associated data.`)) {
                      deleteProject(proj.id);
                    }
                  }}
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      <hr style={{ borderColor: "var(--border-color)" }} />

      {/* Datasets Catalog section */}
      <div style={{ display: "flex", flexDirection: "column", gap: "10px", flex: 1 }}>
        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
          <Database size={14} color="var(--accent-color)" />
          <h3 style={{ fontSize: "14px", fontWeight: "600", textTransform: "uppercase", color: "var(--text-secondary)" }}>
            Available Datasets
          </h3>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: "6px", overflowY: "auto", flex: 1 }}>
          {/* 1. Standalone Files (CSV, JSON, XLSX) */}
          {standaloneDatasets.map((ds) => (
            <div
              key={ds.id}
              className="glass-panel"
              style={{
                display: "flex",
                alignItems: "center",
                gap: "10px",
                padding: "8px 12px",
                cursor: "pointer",
                borderRadius: "8px",
                background: activeDatasetId === ds.id ? "rgba(16, 185, 129, 0.1)" : "var(--bg-card)",
                borderColor: activeDatasetId === ds.id ? "var(--success-color)" : "var(--border-color)",
              }}
              onClick={() => selectDataset(ds.id)}
            >
              <FileSpreadsheet size={16} color={activeDatasetId === ds.id ? "#34d399" : "#9ca3af"} />
              <div style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
                <span style={{ fontSize: "13px", fontWeight: "500", textOverflow: "ellipsis", overflow: "hidden", whiteSpace: "nowrap" }}>
                  {ds.filename}
                </span>
                <span style={{ fontSize: "11px", color: "var(--text-muted)" }}>
                  {ds.row_count > 0 ? `${ds.row_count.toLocaleString()} rows` : "File dataset"}
                </span>
              </div>
            </div>
          ))}

          {/* 2. Database Collapsible Groups (SQLite .db files) */}
          {Object.keys(dbGroups).map((dbName) => {
            const isCollapsed = collapsedDbs[dbName];
            const tables = dbGroups[dbName];

            return (
              <div key={dbName} style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                {/* Database Folder Header (Non-selectable container) */}
                <div
                  className="glass-panel"
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "8px",
                    padding: "8px 12px",
                    cursor: "pointer",
                    borderRadius: "8px",
                    background: "rgba(99, 102, 241, 0.06)",
                    borderColor: "rgba(99, 102, 241, 0.2)",
                  }}
                  onClick={() => toggleDbCollapse(dbName)}
                  title="Click to expand/collapse database tables"
                >
                  {isCollapsed ? <ChevronRight size={14} color="#818cf8" /> : <ChevronDown size={14} color="#818cf8" />}
                  <Database size={15} color="#818cf8" />
                  <div style={{ display: "flex", flexDirection: "column", minWidth: 0, flex: 1 }}>
                    <span style={{ fontSize: "13px", fontWeight: "600", color: "#a5b4fc", textOverflow: "ellipsis", overflow: "hidden", whiteSpace: "nowrap" }}>
                      {dbName}
                    </span>
                    <span style={{ fontSize: "10px", color: "var(--text-muted)" }}>
                      {tables.length} tables
                    </span>
                  </div>
                </div>

                {/* Sub-Tables Tree (Selectable individual dataset entries) */}
                {!isCollapsed && (
                  <div style={{ display: "flex", flexDirection: "column", gap: "4px", paddingLeft: "16px", borderLeft: "1px dashed rgba(255,255,255,0.1)", marginLeft: "12px" }}>
                    {tables.map((tblDs) => (
                      <div
                        key={tblDs.id}
                        className="glass-panel"
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: "8px",
                          padding: "6px 10px",
                          cursor: "pointer",
                          borderRadius: "6px",
                          background: activeDatasetId === tblDs.id ? "rgba(16, 185, 129, 0.15)" : "var(--bg-card)",
                          borderColor: activeDatasetId === tblDs.id ? "var(--success-color)" : "var(--border-color)",
                        }}
                        onClick={() => selectDataset(tblDs.id)}
                      >
                        <TableIcon size={14} color={activeDatasetId === tblDs.id ? "#34d399" : "#9ca3af"} />
                        <div style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
                          <span style={{ fontSize: "12.5px", fontWeight: "500", textOverflow: "ellipsis", overflow: "hidden", whiteSpace: "nowrap" }}>
                            {tblDs.filename}
                          </span>
                          <span style={{ fontSize: "10.5px", color: "var(--text-muted)" }}>
                            {tblDs.row_count > 0 ? `${tblDs.row_count.toLocaleString()} rows` : "Table"}
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}

          {datasets.length === 0 && (
            <div style={{ color: "var(--text-muted)", fontSize: "13px", textAlign: "center", marginTop: "20px" }}>
              No datasets found in catalog (`datasets/`).
            </div>
          )}
        </div>
      </div>
    </aside>
  );
};
export default Sidebar;
