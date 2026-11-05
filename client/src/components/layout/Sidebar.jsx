import React, { useState } from "react";
import { useProject } from "../../context/ProjectContext";
import {
  Folder,
  Library,
  Plus,
  Trash2,
  Edit3,
  FileSpreadsheet,
  Database,
  ChevronDown,
  ChevronRight,
  Table as TableIcon,
} from "lucide-react";

export const Sidebar = ({ onOpenSaved, savedActive }) => {
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
  const [query, setQuery] = useState("");
  const search = query.trim().toLowerCase();
  const standaloneDatasets = [];
  const dbGroups = {};

  datasets.forEach((ds) => {
    if (search && !ds.id.toLowerCase().includes(search) &&
        !ds.filename.toLowerCase().includes(search) &&
        !ds.parent_db?.toLowerCase().includes(search)) return;
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
          <button className="btn btn-secondary" style={{ padding: "4px 8px" }} aria-label="New project" onClick={() => setIsCreating(!isCreating)}>
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
            <div key={proj.id} className="project-row">
              <button type="button" className="nav-item" aria-current={activeProjectId === proj.id || undefined}
                onClick={() => selectProject(proj.id, proj.name)}>
                <Folder size={15} /><span>{proj.name}</span>
              </button>
              <div style={{ display: "flex", gap: "4px" }}>
                <button
                  style={{ background: "transparent", border: "none", color: "var(--text-secondary)", cursor: "pointer" }}
                  aria-label={`Rename ${proj.name}`}
                  onClick={() => handleRename(proj.id, proj.name)}
                >
                  <Edit3 size={14} />
                </button>
                <button
                  style={{ background: "transparent", border: "none", color: "var(--danger-color)", cursor: "pointer" }}
                  aria-label={`Delete ${proj.name}`}
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

      <button type="button" className="nav-item library-nav" aria-current={savedActive || undefined} onClick={onOpenSaved}>
        <Library size={17} /><span>Saved Analyses</span><ChevronRight size={14} />
      </button>

      <section aria-label="Datasets">
        <h3 className="nav-heading">Datasets</h3>
        <input className="input-text dataset-search" type="search" aria-label="Search datasets"
          placeholder="Search datasets" value={query} onChange={(event) => setQuery(event.target.value)} />
        <ul className="dataset-tree">
          {standaloneDatasets.map((dataset) => (
            <li key={dataset.id}>
              <button type="button" className="nav-item" aria-current={activeDatasetId === dataset.id || undefined}
                onClick={() => selectDataset(dataset.id)}>
                <FileSpreadsheet size={15} /><span>{dataset.filename}</span>
              </button>
            </li>
          ))}
          {Object.entries(dbGroups).map(([database, tables]) => {
            const expanded = Boolean(search) || !collapsedDbs[database];
            return (
              <li key={database}>
                <div className="dataset-branch">
                  {!search && (
                    <button type="button" className="nav-item tree-toggle" aria-expanded={expanded}
                      aria-label={`${expanded ? "Collapse" : "Expand"} ${database}`}
                      onClick={() => toggleDbCollapse(database)}>
                      {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                    </button>
                  )}
                  <button type="button" className="nav-item" aria-current={activeDatasetId === database || undefined}
                    onClick={() => selectDataset(database)}>
                    <Database size={15} /><span>{database}</span>
                  </button>
                </div>
                {expanded && (
                  <ul className="dataset-tree dataset-children">
                    {tables.map((dataset) => (
                      <li key={dataset.id}>
                        <button type="button" className="nav-item" aria-current={activeDatasetId === dataset.id || undefined}
                          onClick={() => selectDataset(dataset.id)}>
                          <TableIcon size={14} /><span>{dataset.filename}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            );
          })}
          {!standaloneDatasets.length && !Object.keys(dbGroups).length && (
            <li className="nav-empty">{search ? "No matching datasets" : "No datasets in the catalog"}</li>
          )}
        </ul>
      </section>
    </aside>
  );
};
export default Sidebar;
