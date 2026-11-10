export const STAGES = {
  connecting: "Connecting to the analyst", classifying: "Reading the question",
  planning: "Planning the analysis", repairing_plan: "Checking the analysis plan",
  selecting_tables: "Selecting tables", running_tool: "Running analysis",
  validating: "Verifying the results", preparing_answer: "Preparing the answer",
  publishing: "Saving the answer", completed: "Completed", failed: "Failed",
  incomplete: "Incomplete", unsupported: "Unsupported", clarification: "Needs clarification",
  timed_out: "Timed out", cancelled: "Cancelled",
};
const TERMINAL = new Set(['completed','failed','incomplete','unsupported','clarification','timed_out','cancelled']);
export function progressState(message, now = 0) {
  const meta = message.metadata ?? {};
  const status = message.analysis_status ?? meta.analysis_status;
  const stage = message.stage ?? message.request_stage ?? meta.request_stage ??
    (status === 'complete' || status === 'not_applicable' ? 'completed' : TERMINAL.has(status) ? status : meta.analysis_failed ? 'failed' : undefined);
  const pending = Boolean(message.pending) && !TERMINAL.has(stage);
  const measured = message.elapsedMs ?? message.elapsed_ms ?? meta.elapsed_ms;
  const elapsed = pending && Number.isFinite(message.startedAt) ? Math.max(0, now - message.startedAt) : measured;
  return { stage, pending, elapsed: Number.isFinite(elapsed) ? elapsed : undefined };
}
