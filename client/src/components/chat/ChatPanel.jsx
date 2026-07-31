import React, { useState, useRef, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useProject } from "../../context/ProjectContext";
import { Send, Bot, User, Code, AlertCircle, FileText, Image } from "lucide-react";

export const ChatPanel = () => {
  const { chatHistory, sendChatMessage, chatLoading, activeDatasetId } = useProject();
  const [inputText, setInputText] = useState("");
  const scrollRef = useRef(null);

  const handleSend = (e) => {
    e.preventDefault();
    if (!inputText.trim() || chatLoading) return;
    sendChatMessage(inputText.trim());
    setInputText("");
  };

  // Scroll to bottom on updates
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [chatHistory, chatLoading]);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", position: "relative" }}>
      {/* Header title */}
      <div style={{ padding: "16px", borderBottom: "1px solid var(--border-color)", background: "rgba(0,0,0,0.15)" }}>
        <h3 style={{ fontSize: "14px", fontWeight: "600", textTransform: "uppercase", color: "var(--text-secondary)" }}>
          AI Analyst Chat
        </h3>
      </div>

      {/* Message Feed list */}
      <div style={{ flex: 1, padding: "16px", overflowY: "auto", display: "flex", flexDirection: "column", gap: "16px" }}>
        {chatHistory.length === 0 ? (
          <div style={{ display: "flex", flex: 1, alignItems: "center", justifyContent: "center", height: "100%", flexDirection: "column", color: "var(--text-muted)", fontSize: "13px", gap: "8px" }}>
            <Bot size={36} color="var(--accent-color)" />
            <span>Ask questions about your active dataset.</span>
            <span>Example: "What is the average sales grouped by Month?"</span>
          </div>
        ) : (
          chatHistory.map((msg, index) => {
            const isUser = msg.role === "user";
            
            // Check metadata if exists
            let meta = {};
            if (msg.metadata_json) {
              try {
                meta = JSON.parse(msg.metadata_json);
              } catch (e) {}
            }

            return (
              <div
                key={msg.id || index}
                style={{
                  display: "flex",
                  gap: "12px",
                  flexDirection: isUser ? "row-reverse" : "row",
                  alignItems: "flex-start"
                }}
              >
                {/* Icon wrapper */}
                <div
                  style={{
                    padding: "8px",
                    borderRadius: "50%",
                    background: isUser ? "rgba(99, 102, 241, 0.15)" : "rgba(16, 185, 129, 0.15)",
                    border: "1px solid",
                    borderColor: isUser ? "var(--accent-color)" : "var(--success-color)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center"
                  }}
                >
                  {isUser ? <User size={14} /> : <Bot size={14} />}
                </div>

                {/* Dialog Content Bubble */}
                <div
                  className="glass-panel"
                  style={{
                    padding: "14px",
                    maxWidth: "88%",
                    borderRadius: "12px",
                    fontSize: "13.5px",
                    background: isUser ? "rgba(22, 24, 30, 0.9)" : "rgba(15, 17, 22, 0.95)"
                  }}
                >
                  {/* Message body text with Markdown formatting */}
                  <div className="markdown-content">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
                  </div>

                  {/* Render base64 image if complex execution created a plot */}
                  {meta.chart_base64 && (
                    <div style={{ marginTop: "12px", border: "1px solid var(--border-color)", borderRadius: "8px", overflow: "hidden", background: "#000" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: "6px", padding: "6px", background: "rgba(255,255,255,0.03)", fontSize: "11px", color: "var(--text-secondary)" }}>
                        <Image size={12} />
                        <span>Captured Plotly/Matplotlib Plot</span>
                      </div>
                      <img
                        src={`data:image/png;base64,${meta.chart_base64}`}
                        alt="Captured visual plot"
                        style={{ width: "100%", display: "block" }}
                      />
                    </div>
                  )}
                </div>
              </div>
            );
          })
        )}

        {/* Dynamic chat loader bubble */}
        {chatLoading && (
          <div style={{ display: "flex", gap: "12px", alignItems: "flex-start" }}>
            <div style={{ padding: "8px", borderRadius: "50%", background: "rgba(16, 185, 129, 0.15)", border: "1px solid var(--success-color)" }}>
              <Bot size={14} />
            </div>
            <div className="glass-panel" style={{ padding: "12px", borderRadius: "12px", display: "flex", alignItems: "center", gap: "10px" }}>
              <div className="spinner"></div>
              <span style={{ fontSize: "13px", color: "var(--text-secondary)" }}>Analysing query instructions...</span>
            </div>
          </div>
        )}
        <div ref={scrollRef} />
      </div>

      {/* Input container footer */}
      <form onSubmit={handleSend} style={{ padding: "16px", borderTop: "1px solid var(--border-color)", background: "rgba(0,0,0,0.15)", display: "flex", gap: "8px" }}>
        <input
          type="text"
          className="input-text"
          placeholder={activeDatasetId ? "Type question about dataset..." : "Select active dataset first..."}
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          disabled={!activeDatasetId || chatLoading}
        />
        <button
          className="btn btn-primary"
          style={{ padding: "10px" }}
          type="submit"
          disabled={!activeDatasetId || chatLoading || !inputText.trim()}
        >
          <Send size={16} />
        </button>
      </form>
    </div>
  );
};
export default ChatPanel;
