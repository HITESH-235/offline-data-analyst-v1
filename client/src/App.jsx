import React, { useState, useEffect, useCallback } from "react";
import Sidebar from "./components/layout/Sidebar";
import DatasetViewer from "./components/dataset/DatasetViewer";
import ChatPanel from "./components/chat/ChatPanel";
import { useProject } from "./context/ProjectContext";
import {
  Terminal,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
} from "lucide-react";

function App() {
  const { activeProjectId, activeProjectName, activeDatasetId, datasets } = useProject();

  const [workspaceView, setWorkspaceView] = useState("data");

  const [resultByProject, setResultByProject] = useState({});
  const [tabByProject, setTabByProject] = useState({});
  const activeTab = tabByProject[activeProjectId] ?? "preview";

  function setActiveTab(tab) {
    setTabByProject((previous) => ({ ...previous, [activeProjectId]: tab }));
  }

  function openResult(result) {
    setResultByProject((previous) => ({ ...previous, [activeProjectId]: { ...result, openId: crypto.randomUUID() } }));
    setActiveTab("result");
    setWorkspaceView("data");
  }

  const activeDataset = datasets.find((d) => d.id === activeDatasetId);
  const datasetNameLabel = activeDataset?.filename || activeDatasetId || "None";

  // Left Sidebar State (width & visibility)
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    const saved = localStorage.getItem("sidebarWidth");
    return saved ? parseInt(saved, 10) : 228;
  });
  const [isSidebarOpen, setIsSidebarOpen] = useState(() => {
    const saved = localStorage.getItem("isSidebarOpen");
    return saved !== null ? JSON.parse(saved) : true;
  });

  // Right Chat Panel State (width & visibility)
  const [chatWidth, setChatWidth] = useState(() => {
    const saved = localStorage.getItem("chatWidth");
    return saved ? parseInt(saved, 10) : 320;
  });
  const [isChatOpen, setIsChatOpen] = useState(() => {
    const saved = localStorage.getItem("isChatOpen");
    return saved !== null ? JSON.parse(saved) : true;
  });

  // Resizing state ("left" | "right" | null)
  const [resizingPanel, setResizingPanel] = useState(null);

  const startResizingLeft = useCallback((e) => {
    e.preventDefault();
    setResizingPanel("left");
  }, []);

  const startResizingRight = useCallback((e) => {
    e.preventDefault();
    setResizingPanel("right");
  }, []);

  useEffect(() => {
    const handleMouseMove = (e) => {
      if (!resizingPanel) return;

      if (resizingPanel === "left") {
        const newWidth = Math.min(Math.max(e.clientX, 180), 500);
        setSidebarWidth(newWidth);
        localStorage.setItem("sidebarWidth", newWidth);
      } else if (resizingPanel === "right") {
        const newWidth = Math.min(Math.max(window.innerWidth - e.clientX, 280), 650);
        setChatWidth(newWidth);
        localStorage.setItem("chatWidth", newWidth);
      }
    };

    const handleMouseUp = () => {
      if (resizingPanel) {
        setResizingPanel(null);
      }
    };

    if (resizingPanel) {
      window.addEventListener("mousemove", handleMouseMove);
      window.addEventListener("mouseup", handleMouseUp);
    }

    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, [resizingPanel]);

  const toggleSidebar = () => {
    setIsSidebarOpen((prev) => {
      const next = !prev;
      localStorage.setItem("isSidebarOpen", JSON.stringify(next));
      return next;
    });
  };

  const toggleChat = () => {
    setIsChatOpen((prev) => {
      const next = !prev;
      localStorage.setItem("isChatOpen", JSON.stringify(next));
      return next;
    });
  };

  const leftCol = isSidebarOpen ? `${sidebarWidth}px` : "0px";
  const rightCol = isChatOpen ? `${chatWidth}px` : "0px";

  return (
    <div
      className={`app-container view-${workspaceView} ${resizingPanel ? "resizing" : ""}`}
      style={{ "--left-column": leftCol, "--right-column": rightCol }}
    >
      {/* Top Header section */}
      <header className="header">
        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          <button
            className="btn btn-secondary icon-only-btn desktop-panel-toggle"
            aria-expanded={isSidebarOpen}
            onClick={toggleSidebar}
            title={isSidebarOpen ? "Collapse Projects Sidebar" : "Expand Projects Sidebar"}
            style={{ padding: "6px" }}
          >
            {isSidebarOpen ? <PanelLeftClose size={18} /> : <PanelLeftOpen size={18} />}
          </button>

          <div className="header-logo">
            <Terminal size={22}  />
            <span>Offline AI Data Analyst</span>
          </div>
        </div>

        <div style={{ display: "flex", gap: "20px", alignItems: "center", fontSize: "13px" }}>
          <div>
            <span style={{ color: "var(--text-muted)", marginRight: "6px" }}>Active Project:</span>
            <span style={{ fontWeight: "600", color: "var(--text-primary)" }}>
              {activeProjectName || "None"}
            </span>
          </div>

          <button
            className="btn btn-secondary icon-only-btn desktop-panel-toggle"
            aria-expanded={isChatOpen}
            onClick={toggleChat}
            title={isChatOpen ? "Collapse AI Chat Panel" : "Expand AI Chat Panel"}
            style={{ padding: "6px" }}
          >
            {isChatOpen ? <PanelRightClose size={18} /> : <PanelRightOpen size={18} />}
          </button>
        </div>
      </header>

      <nav className="workspace-nav" aria-label="Workspace view">
        {["Projects", "Data", "Chat"].map((view) => (
          <button
            key={view}
            type="button"
            className="btn btn-secondary"
            aria-pressed={workspaceView === view.toLowerCase()}
            onClick={() => setWorkspaceView(view.toLowerCase())}
          >
            {view}
          </button>
        ))}
      </nav>

      {/* Left Sidebar Column */}
      <div
        className={`workspace-projects ${isSidebarOpen ? "" : "panel-collapsed"}`}
        style={{
          position: "relative",
          height: "100%",
          overflow: "hidden",
        }}
      >
        <Sidebar savedActive={activeTab === "saved"} onOpenSaved={() => { setActiveTab("saved"); setWorkspaceView("data"); }} />
        {/* Left Drag Resizer Handle */}
        <div
          className={`sidebar-resizer left ${resizingPanel === "left" ? "active" : ""}`}
          onMouseDown={startResizingLeft}
          title="Drag to resize sidebar"
        />
      </div>

      {/* Center Main Content Area */}
      <main className="center-panel">
        <div className="workspace-surface">
          <DatasetViewer onOpenResult={openResult} datasetName={datasetNameLabel} activeTab={activeTab} setActiveTab={setActiveTab} selectedResult={resultByProject[activeProjectId]} />
        </div>
      </main>

      {/* Right Chat Panel Column */}
      <div
        className={`workspace-chat ${isChatOpen ? "" : "panel-collapsed"}`}
        style={{
          position: "relative",
          height: "100%",
          overflow: "hidden",
        }}
      >
        {/* Right Drag Resizer Handle */}
        <div
          className={`sidebar-resizer right ${resizingPanel === "right" ? "active" : ""}`}
          onMouseDown={startResizingRight}
          title="Drag to resize AI chat panel"
        />
        <section className="right-panel" style={{ height: "100%" }}>
          <ChatPanel datasetName={activeDataset?.filename} onOpenResult={openResult} />
        </section>
      </div>
    </div>
  );
}

export default App;
