import React, { useState, useEffect, useCallback } from "react";
import Sidebar from "./components/layout/Sidebar";
import DatasetViewer from "./components/dataset/DatasetViewer";
import ChatPanel from "./components/chat/ChatPanel";
import { useProject } from "./context/ProjectContext";
import {
  Terminal,
  Database,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
} from "lucide-react";

function App() {
  const { activeProjectName, activeDatasetId, datasets } = useProject();

  const activeDataset = datasets.find((d) => d.id === activeDatasetId);
  const datasetNameLabel = activeDataset ? activeDataset.filename : "None";

  // Left Sidebar State (width & visibility)
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    const saved = localStorage.getItem("sidebarWidth");
    return saved ? parseInt(saved, 10) : 280;
  });
  const [isSidebarOpen, setIsSidebarOpen] = useState(() => {
    const saved = localStorage.getItem("isSidebarOpen");
    return saved !== null ? JSON.parse(saved) : true;
  });

  // Right Chat Panel State (width & visibility)
  const [chatWidth, setChatWidth] = useState(() => {
    const saved = localStorage.getItem("chatWidth");
    return saved ? parseInt(saved, 10) : 400;
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
      className={`app-container ${resizingPanel ? "resizing" : ""}`}
      style={{ gridTemplateColumns: `${leftCol} 1fr ${rightCol}` }}
    >
      {/* Top Header section */}
      <header className="header">
        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          <button
            className="btn btn-secondary icon-only-btn"
            onClick={toggleSidebar}
            title={isSidebarOpen ? "Collapse Projects Sidebar" : "Expand Projects Sidebar"}
            style={{ padding: "6px" }}
          >
            {isSidebarOpen ? <PanelLeftClose size={18} /> : <PanelLeftOpen size={18} />}
          </button>

          <div className="header-logo">
            <Terminal size={22} color="#818cf8" />
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

          {activeDatasetId && (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: "6px",
                background: "rgba(255,255,255,0.03)",
                padding: "4px 10px",
                borderRadius: "20px",
                border: "1px solid var(--border-color)",
              }}
            >
              <Database size={13} color="#10b981" />
              <span style={{ fontWeight: "500", color: "var(--success-color)" }}>
                {datasetNameLabel}
              </span>
            </div>
          )}

          <button
            className="btn btn-secondary icon-only-btn"
            onClick={toggleChat}
            title={isChatOpen ? "Collapse AI Chat Panel" : "Expand AI Chat Panel"}
            style={{ padding: "6px" }}
          >
            {isChatOpen ? <PanelRightClose size={18} /> : <PanelRightOpen size={18} />}
          </button>
        </div>
      </header>

      {/* Left Sidebar Column */}
      <div
        style={{
          position: "relative",
          height: "100%",
          overflow: "hidden",
          display: isSidebarOpen ? "block" : "none",
        }}
      >
        <Sidebar />
        {/* Left Drag Resizer Handle */}
        <div
          className={`sidebar-resizer left ${resizingPanel === "left" ? "active" : ""}`}
          onMouseDown={startResizingLeft}
          title="Drag to resize sidebar"
        />
      </div>

      {/* Center Main Content Area */}
      <main className="center-panel">
        <div className="glass-panel" style={{ flex: 1, padding: "20px", minHeight: 0 }}>
          <DatasetViewer />
        </div>
      </main>

      {/* Right Chat Panel Column */}
      <div
        style={{
          position: "relative",
          height: "100%",
          overflow: "hidden",
          display: isChatOpen ? "block" : "none",
        }}
      >
        {/* Right Drag Resizer Handle */}
        <div
          className={`sidebar-resizer right ${resizingPanel === "right" ? "active" : ""}`}
          onMouseDown={startResizingRight}
          title="Drag to resize AI chat panel"
        />
        <section className="right-panel" style={{ height: "100%" }}>
          <ChatPanel />
        </section>
      </div>
    </div>
  );
}

export default App;
