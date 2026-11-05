import React, { useState, useRef, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import CalculationDetails from "./CalculationDetails";
import { useProject } from "../../context/ProjectContext";
import { Send, Bot, User, Image, ArrowUpRight } from "lucide-react";

const STAGES = {
  connecting: "Connecting to the analyst",
  classifying: "Reading the question",
  selecting_tables: "Selecting tables",
  running_tool: "Running analysis",
  preparing_answer: "Preparing the answer",
  completed: "Completed",
  failed: "Failed",
};

function ChatProgress({ message }) {
  const [now, setNow] = useState(() => performance.now());
  useEffect(() => {
    if (!message.pending) return;
    const timer = setInterval(() => setNow(performance.now()), 250);
    return () => clearInterval(timer);
  }, [message.pending]);
  const elapsed = message.elapsedMs ?? Math.max(0, now - message.startedAt);
  return (
    <div className="chat-progress">
      <span role="status" title={message.datasetName}>{STAGES[message.stage]} · {message.datasetName}</span>
      <span className="elapsed">{(elapsed / 1000).toFixed(1)} s</span>
    </div>
  );
}

export const ChatPanel = ({ datasetName, onOpenResult }) => {
  const { chatHistory, sendChatMessage, chatLoading, activeDatasetId } = useProject();
  const [inputText, setInputText] = useState("");
  const scrollRef = useRef(null);
  const inputRef = useRef(null);
  const canSend = Boolean(activeDatasetId) && !chatLoading;

  const handleSend = (e) => {
    e.preventDefault();
    if (!inputText.trim() || !canSend) return;
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
      <div className="analyst-heading" style={{ padding: "16px", borderBottom: "1px solid var(--border-color)", background: "var(--bg-card)" }}>
        <h3 style={{ fontSize: "14px", fontWeight: "600", textTransform: "uppercase", color: "var(--text-secondary)" }}>
          AI Analyst
        </h3>
        <span className="eyebrow">Ask · explore · understand</span>
        <p className="chat-dataset" title={datasetName}>{datasetName || "Select a dataset to start"}</p>
      </div>

      {/* Message Feed list */}
      <div style={{ flex: 1, padding: "16px", overflowY: "auto", display: "flex", flexDirection: "column", gap: "16px" }}>
        {chatHistory.length === 0 ? (
          <div style={{ display: "flex", flex: 1, alignItems: "center", justifyContent: "center", height: "100%", flexDirection: "column", color: "var(--text-muted)", fontSize: "13px", gap: "8px" }}>
            <Bot size={36} color="var(--accent-color)" />
            <span>{activeDatasetId ? "Start with a question about your data." : "Choose a dataset in Projects."}</span>
            {activeDatasetId && ["Summarize this dataset.", "Which columns have missing values?"].map((question) => (
              <button
                key={question}
                type="button"
                className="btn btn-secondary"
                disabled={!canSend}
                onClick={() => {
                  setInputText(question);
                  inputRef.current?.focus();
                }}
              >
                {question}
              </button>
            ))}
          </div>
        ) : (
          chatHistory.map((msg, index) => {
            const isUser = msg.role === "user";
            
            // Check metadata if exists
            let meta = {};
            if (msg.metadata_json) {
              try {
                meta = JSON.parse(msg.metadata_json) ?? {};
              } catch {
                // Older messages may not have valid metadata.
              }
            }

            const calculation = msg.calculation ?? meta.calculation;
            const result = msg.results ?? meta.results;
            const resultStep = calculation?.steps?.findLast(
              (step) => step.status === "succeeded" && step.tool !== "run_code"
            );

            const narrativeStatistics = resultStep?.tool === "statistics" && resultStep?.parameters?.return_table !== true;
            const hasResult = !narrativeStatistics && Array.isArray(result?.data) && result?.columns?.length > 0;
            const tables = resultStep?.tables ?? (msg.datasetId ? [msg.datasetId] : []);

            return (
              <div
                key={msg.id || index}
                className={`chat-turn ${isUser ? "user-turn" : "analyst-turn"}`}
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
                    background: "var(--accent-glow)",
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
                  className={`glass-panel chat-message ${msg.pending ? "chat-pending" : ""}`}
                  style={{
                    padding: "14px",
                    maxWidth: "88%",
                    minWidth: 0,
                    overflowWrap: "anywhere",
                    borderRadius: "12px",
                    fontSize: "13.5px",
                    background: isUser ? "var(--accent-glow)" : "var(--bg-card)"
                  }}
                >
                  <div className="message-author">{isUser ? "You" : "Analyst"}</div>
                  {msg.stage && <ChatProgress message={msg} />}

                  {/* Message body text with Markdown formatting */}
                  <div className="markdown-content">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content ?? ""}</ReactMarkdown>
                  </div>

                  {hasResult && (
                    <button
                      type="button"
                      className="btn btn-secondary chat-result-card"
                      onClick={() => onOpenResult({ id: msg.id, result, tables, calculation })}
                    >
                      <strong>Open result <ArrowUpRight size={15} aria-hidden="true" /></strong>
                      <span>{tables.join(" · ") || "Source unavailable"}</span>
                      <span>{result.data.length.toLocaleString()} rows</span>
                    </button>
                  )}

                  {!hasResult && <CalculationDetails calculation={calculation} />}

                  {/* Render base64 image if complex execution created a plot */}
                  {meta.chart_base64 && (
                    <div style={{ marginTop: "12px", border: "1px solid var(--border-color)", borderRadius: "8px", overflow: "hidden", background: "var(--bg-card)" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: "6px", padding: "6px", background: "var(--bg-main)", fontSize: "11px", color: "var(--text-secondary)" }}>
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

        <div ref={scrollRef} />
      </div>

      {/* Input container footer */}
      <form className="chat-composer" onSubmit={handleSend} style={{ padding: "16px", borderTop: "1px solid var(--border-color)", background: "var(--bg-card)", display: "flex", gap: "8px" }}>
        <textarea
          ref={inputRef}
          rows={2}
          aria-label="Question for the analyst"
          className="input-text"
          placeholder={activeDatasetId ? "Ask a question about your data…" : "Select a dataset first"}
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              handleSend(e);
            }
          }}
          disabled={!activeDatasetId}
        />
        <button
          className="btn btn-primary"
          style={{ padding: "10px" }}
          type="submit"
          aria-label="Send question"
          disabled={!canSend || !inputText.trim()}
        >
          <Send size={16} />
        </button>
      </form>
    </div>
  );
};
export default ChatPanel;
