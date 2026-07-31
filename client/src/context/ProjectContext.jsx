import React, { createContext, useState, useEffect, useContext } from "react";

const ProjectContext = createContext(null);

const BACKEND_URL = "http://127.0.0.1:8000/api/v1";

export const ProjectProvider = ({ children }) => {
  const [projects, setProjects] = useState([]);
  const [activeProjectId, setActiveProjectId] = useState(null);
  const [activeProjectName, setActiveProjectName] = useState("");
  const [datasets, setDatasets] = useState([]);
  const [activeDatasetId, setActiveDatasetId] = useState(null);
  const [activeDatasetPreview, setActiveDatasetPreview] = useState(null);
  const [activeDatasetProfile, setActiveDatasetProfile] = useState(null);
  const [chatHistory, setChatHistory] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [chatLoading, setChatLoading] = useState(false);

  // 1. Fetch Projects List
  const loadProjects = async () => {
    try {
      const response = await fetch(`${BACKEND_URL}/projects`);
      if (response.ok) {
        const data = await response.json();
        setProjects(data);
        if (data.length > 0 && !activeProjectId) {
          selectProject(data[0].id, data[0].name);
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
    setChatHistory([]);
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
    setActiveDatasetId(datasetId);
    setIsLoading(true);
    try {
      // Get preview
      const prevResp = await fetch(`${BACKEND_URL}/datasets/${datasetId}/preview`);
      if (prevResp.ok) {
        const prevData = await prevResp.json();
        setActiveDatasetPreview(prevData);
      }
      
      // Get profile
      const profResp = await fetch(`${BACKEND_URL}/datasets/${datasetId}/profile`);
      if (profResp.ok) {
        const profData = await profResp.json();
        setActiveDatasetProfile(profData);
      }
    } catch (error) {
      console.error("Load dataset details failed:", error);
    } finally {
      setIsLoading(false);
    }
  };

  // 8. Post Chat Message
  const sendChatMessage = async (msg) => {
    if (!activeProjectId || !activeDatasetId) {
      alert("Please select a project and dataset first.");
      return;
    }
    
    const userMsgObj = {
      id: Date.now().toString(),
      role: "user",
      content: msg,
      created_at: new Date().toISOString()
    };
    
    setChatHistory(prev => [...prev, userMsgObj]);
    setChatLoading(true);

    try {
      const response = await fetch(`${BACKEND_URL}/chat/message`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: activeProjectId,
          dataset_id: activeDatasetId,
          message: msg
        })
      });
      
      if (response.ok) {
        const assistantMsg = await response.json();
        setChatHistory(prev => [...prev, assistantMsg]);
      }
    } catch (error) {
      console.error("Chat message delivery failed:", error);
    } finally {
      setChatLoading(false);
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
      generateReport
    }}>
      {children}
    </ProjectContext.Provider>
  );
};

export const useProject = () => useContext(ProjectContext);
