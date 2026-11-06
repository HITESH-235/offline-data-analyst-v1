import React, { useState, useRef, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import CalculationDetails from "./CalculationDetails";
import { useProject } from "../../context/ProjectContext";
import { Send, Bot, User, ArrowUpRight } from "lucide-react";

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
  const { chatHistory, sendChatMessage, chatLoading, activeDatasetId, activeProjectId, loadChatHistory } = useProject();
  const [showPast, setShowPast] = useState(false);
  const [past, setPast] = useState(null);
  const [pastError, setPastError] = useState('');
  const [loadingPast, setLoadingPast] = useState(false);
  useEffect(() => {
    if (!showPast) return;
    const controller = new AbortController();
    setPast(null); setPastError(''); setLoadingPast(true);
    loadChatHistory(activeProjectId, null, controller.signal).then(page => {
      if (!controller.signal.aborted) setPast({ ...page, projectId: activeProjectId });
    }).catch(error => { if (!controller.signal.aborted) setPastError(error.message); })
      .finally(() => { if (!controller.signal.aborted) setLoadingPast(false); });
    return () => controller.abort();
  }, [showPast, activeProjectId, loadChatHistory]);
  useEffect(() => {
    const deleted = ({ detail }) => setPast(previous => {
      if (previous?.projectId !== detail.projectId) return previous;
      return { ...previous, messages: previous.messages.map(message => {
        if (message.id !== detail.analysisId) return message;
        let metadata = {}; try { metadata = JSON.parse(message.metadata_json || '{}'); } catch { /* Legacy metadata. */ }
        delete metadata.results; delete metadata.chart_base64; delete metadata.artifacts; metadata.analysis_deleted = true;
        return { ...message, metadata_json: JSON.stringify(metadata) };
      }) };
    });
    window.addEventListener('analysis-deleted', deleted);
    return () => window.removeEventListener('analysis-deleted', deleted);
  }, []);
  useEffect(() => {
    if (showPast && past?.projectId === activeProjectId) scrollRef.current?.scrollIntoView();
  }, [showPast, past?.projectId, activeProjectId]);
  const older = async () => {
    const projectId = activeProjectId; setLoadingPast(true); setPastError('');
    try {
      const page = await loadChatHistory(projectId, past.before);
      setPast(previous => previous?.projectId === projectId ? { ...page, projectId, messages: [...page.messages, ...previous.messages] } : previous);
    } catch (error) { setPastError(error.message); }
    finally { setLoadingPast(false); }
  };
  const visibleHistory = showPast ? (past?.projectId === activeProjectId ? past.messages : []) : chatHistory;
  const [inputText, setInputText] = useState("");
  const scrollRef = useRef(null);
  const inputRef = useRef(null);
  const canSend = Boolean(activeDatasetId && activeProjectId) && !chatLoading;

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
        <button className="btn btn-secondary past-chat-toggle" aria-pressed={showPast} onClick={() => setShowPast(value => !value)}>{showPast ? "Back to current chat" : "Past chats"}</button>
        <p className="chat-dataset" title={datasetName}>{datasetName || "Select a dataset to start"}</p>
      </div>

      {/* Message Feed list */}
      <div style={{ flex: 1, padding: "16px", overflowY: "auto", display: "flex", flexDirection: "column", gap: "16px" }}>
        {showPast && <div className="past-chat-status"><p>Saved conversation · {visibleHistory.length} messages loaded</p>{loadingPast && <p role="status">Loading past chats…</p>}{pastError && <p role="alert">{pastError}</p>}{past?.has_more && <button className="btn btn-secondary" disabled={loadingPast} onClick={older}>Load older messages</button>}</div>}
        {showPast && !visibleHistory.length ? <p>{loadingPast ? "" : "No saved messages for this project."}</p> : visibleHistory.length === 0 ? (
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
          visibleHistory.map((msg, index) => {
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
            const artifacts = msg.artifacts ?? meta.artifacts ?? [];
            const sourceStep = artifacts.length ? calculation?.steps?.findLast(step => step.status === 'succeeded') : resultStep;
            const canOpen = hasResult || artifacts.length > 0;
            const tables = sourceStep?.tables ?? (msg.datasetId ? [msg.datasetId] : []);

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
                  <div className="message-author">{isUser ? "You" : "Analyst"}{showPast && msg.created_at && <time className="past-message-time" dateTime={msg.created_at}>{new Date(msg.created_at).toLocaleString()}</time>}</div>
                  {msg.stage && <ChatProgress message={msg} />}

                  {/* Message body text with Markdown formatting */}
                  <div className="markdown-content">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content ?? ""}</ReactMarkdown>
                  </div>

                  {canOpen && (
                    <button
                      type="button"
                      className="btn btn-secondary chat-result-card"
                      onClick={() => onOpenResult({ id: msg.savedMessageId ?? msg.id, result, artifacts, tables, calculation, question: msg.question ?? meta.question })}
                    >
                      <strong>Open result <ArrowUpRight size={15} aria-hidden="true" /></strong>
                      <span>{tables.join(" · ") || "Source unavailable"}</span>
                      <span>{hasResult ? `${result.data.length.toLocaleString()} rows` : `${artifacts.length} generated chart${artifacts.length === 1 ? "" : "s"}`}</span>
                    </button>
                  )}

                  {(msg.analysis_deleted || meta.analysis_deleted) && <p className="chart-footnote">This analysis was deleted.</p>}
                  {!canOpen && <CalculationDetails calculation={calculation} />}

                  {meta.chart_base64 && !artifacts.length && <p className="chart-footnote">This older chart has no typed artifact and cannot be safely previewed. Generate it again to open it in Result.</p>}
                </div>
              </div>
            );
          })
        )}

        <div ref={scrollRef} />
      </div>

      {/* Input container footer */}
      {!showPast && <form className="chat-composer" onSubmit={handleSend} style={{ padding: "16px", borderTop: "1px solid var(--border-color)", background: "var(--bg-card)", display: "flex", gap: "8px" }}>
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
      </form>}
    </div>
  );
};
export default ChatPanel;
