import React, { createContext, useState, useEffect, useContext, useRef } from "react";

import { requestWatchdog } from "./requestWatchdog.js";

const ProjectContext = createContext(null);

const BACKEND_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000/api/v1";

async function loadSavedAnalyses(projectId, signal) {
    const response = await fetch(`${BACKEND_URL}/projects/${encodeURIComponent(projectId)}/analyses`, { signal });
    if (!response.ok) throw new Error("Could not load saved analyses.");
    return response.json();
}

async function loadChatHistory(projectId, before, signal) {
  const suffix = before ? `?before=${encodeURIComponent(before)}` : '';
  const response = await fetch(`${BACKEND_URL}/projects/${encodeURIComponent(projectId)}/messages${suffix}`, { signal });
  if (!response.ok) throw new Error("Could not load past chats.");
  return response.json();
}

export const ProjectProvider = ({ children }) => {
  const [projects, setProjects] = useState([]);
  const [activeProjectId, setActiveProjectId] = useState(null);
  const [activeProjectName, setActiveProjectName] = useState("Default Project");
  const [datasets, setDatasets] = useState([]);
  const [activeDatasetId, setActiveDatasetId] = useState("northwind.db");
  const [activeDatasetPreview, setActiveDatasetPreview] = useState(null);
  const [activeDatasetProfile, setActiveDatasetProfile] = useState(null);
  const [historyByProject, setHistoryByProject] = useState({});
  const chatHistory = historyByProject[activeProjectId] ?? [];
  const datasetRequest = useRef(0);
  const pendingProjects = useRef(new Set());
  const [isLoading, setIsLoading] = useState(false);
  const chatLoading = chatHistory.some((message) => message.pending);

  const deleteSavedAnalysis = async (projectId, analysisId) => {
    const response = await fetch(`${BACKEND_URL}/projects/${encodeURIComponent(projectId)}/analyses/${encodeURIComponent(analysisId)}`, { method: 'DELETE' });
    if (!response.ok) throw new Error('Could not delete this saved analysis. Try again.');
    setHistoryByProject(previous => ({ ...previous, [projectId]: (previous[projectId] || []).map(message => {
      if (message.id !== analysisId && message.savedMessageId !== analysisId) return message;
      return { ...message, results: null, artifacts: [], analysis_package:null, analysis_deleted: true };
    }) }));
    window.dispatchEvent(new CustomEvent('analysis-deleted', { detail: { projectId, analysisId } }));
  };

  // 1. Fetch Projects List
  const loadProjects = async () => {
    try {
      const response = await fetch(`${BACKEND_URL}/projects`);
      if (response.ok) {
        const data = await response.json();
        setProjects(data);
        if (data.length > 0) {
          if (!data.some(project => project.id === activeProjectId)) {
            selectProject(data[0].id, data[0].name);
          }
        } else {
          // Auto-create default project if none exists
          await createProject("Default Project");
        }
      }
    } catch (error) {
      console.error("Failed to load projects:", error);
    }
  };

  // 2. Fetch Fixed Datasets Catalog
  const loadCatalogDatasets = async () => {
    try {
      const response = await fetch(`${BACKEND_URL}/datasets/catalog`);
      if (response.ok) {
        const data = await response.json();
        setDatasets(data);
        if (data.length > 0 && !activeDatasetId) {
          selectDataset(data[0].id);
        }
      }
    } catch (error) {
      console.error("Failed to fetch dataset catalog:", error);
    }
  };

  // 3. Select Active Project
  const selectProject = async (id, name) => {
    setActiveProjectId(id);
    setActiveProjectName(name);
    loadCatalogDatasets();
  };

  // 4. Create Project
  const createProject = async (name) => {
    setIsLoading(true);
    try {
      const response = await fetch(`${BACKEND_URL}/projects/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name })
      });
      if (response.ok) {
        const newProj = await response.json();
        await loadProjects();
        selectProject(newProj.id, newProj.name);
        return newProj;
      }
    } catch (error) {
      console.error("Create project failed:", error);
    } finally {
      setIsLoading(false);
    }
  };

  // 5. Rename Project
  const renameProject = async (id, newName) => {
    try {
      const response = await fetch(`${BACKEND_URL}/projects/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ new_name: newName })
      });
      if (response.ok) {
        const updated = await response.json();
        await loadProjects();
        if (activeProjectId === id) {
          setActiveProjectName(updated.name);
        }
      }
    } catch (error) {
      console.error("Rename project failed:", error);
    }
  };

  // 6. Delete Project
  const deleteProject = async (id) => {
    try {
      const response = await fetch(`${BACKEND_URL}/projects/${id}`, {
        method: "DELETE"
      });
      if (response.ok) {
        await loadProjects();
        if (activeProjectId === id) {
          setActiveProjectId(null);
          setActiveProjectName("");
        }
      }
    } catch (error) {
      console.error("Delete project failed:", error);
    }
  };

  // 7. Select Catalog Dataset
  const selectDataset = async (datasetId) => {
    const request = ++datasetRequest.current;
    setActiveDatasetId(datasetId);
    setActiveDatasetPreview(null);
    setActiveDatasetProfile(null);
    setIsLoading(true);
    try {
      // Get preview
      const prevResp = await fetch(`${BACKEND_URL}/datasets/${datasetId}/preview`);
      if (prevResp.ok) {
        const prevData = await prevResp.json();
        if (request === datasetRequest.current) setActiveDatasetPreview(prevData);
      }
      
      // Get profile
      const profResp = await fetch(`${BACKEND_URL}/datasets/${datasetId}/profile`);
      if (profResp.ok) {
        const profData = await profResp.json();
        if (request === datasetRequest.current) setActiveDatasetProfile(profData);
      }
    } catch (error) {
      console.error("Load dataset details failed:", error);
    } finally {
      if (request === datasetRequest.current) setIsLoading(false);
    }
  };

  // 8. Post Chat Message
  const sendChatMessage = async (msg) => {
    if (!activeProjectId) return;
    const projId = activeProjectId;
    const dsId = activeDatasetId || "northwind.db";
    if (pendingProjects.current.has(projId)) return;
    pendingProjects.current.add(projId);

    const id = crypto.randomUUID();
    const pendingId = id + "-reply";
    const startedAt = performance.now();
    const datasetName = datasets.find((dataset) => dataset.id === dsId)?.filename || dsId;
    const updateHistory = (update) => setHistoryByProject((previous) => ({
      ...previous,
      [projId]: update(previous[projId] ?? []),
    }));
    const updateReply = (update) => updateHistory((messages) => messages.map(
      (message) => message.id === pendingId ? { ...message, ...update } : message
    ));
    updateHistory((messages) => [
      ...messages,
      { id, role: "user", content: msg },
      { id: pendingId, role: "assistant", pending: true, startedAt, datasetId: dsId, datasetName, stage: "connecting" },
    ]);

    const watchdog = requestWatchdog((Number(import.meta.env.VITE_CHAT_REQUEST_TIMEOUT_SECONDS) || 135) * 1000);
    try {
      const response = await watchdog.wait(fetch(`${BACKEND_URL}/chat/message/stream`, {
        signal: watchdog.signal,
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: projId, dataset_id: dsId, message: msg }),
      }));
      const serverBudget = Number(response.headers.get("X-Request-Timeout-Seconds"));
      if (serverBudget > 0) watchdog.setBudget((serverBudget + 5) * 1000);
      if (!response.ok || !response.body) throw new Error("Could not start the analysis.");

      let buffer = "";
      const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
      try {
        while (true) {
          const { value, done } = await watchdog.wait(reader.read());
          if (done) throw new Error("The connection closed before the analyst finished.");
          buffer += value;
          const lines = buffer.split("\n");
          buffer = lines.pop();
          for (const line of lines) {
            if (!line.trim()) continue;
            const event = JSON.parse(line);
            if (event.stage === "unsupported" || event.stage === "completed" || event.stage === "failed" || event.stage === "incomplete" || event.stage === "clarification" || event.stage === "timed_out" || event.stage === "cancelled") {
              const result = event.result ?? {};
              updateReply({
                ...result,
                id: pendingId,
                savedMessageId: result.id,
                content: result.content ?? event.error ?? "The analysis failed.",
                pending: false,
                stage: event.stage,
                elapsedMs: performance.now() - startedAt,
              });
              return;
            }
            updateReply({ stage: event.stage });
          }
        }
      } finally {
        reader.cancel().catch(() => {});
      }
    } catch (error) {
      updateReply({ pending: false, stage: watchdog.expired ? "timed_out" : "failed", content: error.message, elapsedMs: performance.now() - startedAt });
    } finally {
      watchdog.dispose();
      pendingProjects.current.delete(projId);
    }
  };

  // 9. Generate Executive Report
  const generateReport = async (title, content) => {
    if (!activeProjectId) return;
    try {
      const response = await fetch(`${BACKEND_URL}/analysis/reports/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: activeProjectId,
          title,
          content
        })
      });
      if (response.ok) {
        return await response.json();
      }
    } catch (error) {
      console.error("Report generation failed:", error);
    }
  };

  // Initial load
  useEffect(() => {
    loadProjects();
    loadCatalogDatasets();
  }, []);

  return (
    <ProjectContext.Provider value={{
      projects,
      activeProjectId,
      activeProjectName,
      datasets,
      activeDatasetId,
      activeDatasetPreview,
      activeDatasetProfile,
      chatHistory,
      isLoading,
      chatLoading,
      createProject,
      renameProject,
      deleteProject,
      selectProject,
      selectDataset,
      sendChatMessage,
      loadSavedAnalyses,
      deleteSavedAnalysis,
      loadChatHistory,
      generateReport
    }}>
      {children}
    </ProjectContext.Provider>
  );
};

export const useProject = () => useContext(ProjectContext);
