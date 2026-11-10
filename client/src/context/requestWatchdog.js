// Covers fetch, response headers and stalled stream reads with one total budget.
export function requestWatchdog(milliseconds) {
  const controller = new AbortController();
  const started = Date.now();
  let timer;
  let rejectDeadline;
  let expired = false;
  const deadline = new Promise((_, reject) => { rejectDeadline = reject; });
  deadline.catch(() => {});
  const setBudget = (budget) => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      expired = true;
      rejectDeadline(new Error('The analysis reached its request deadline. Please try again.'));
      controller.abort();
    }, Math.max(0, budget - (Date.now() - started)));
  };
  setBudget(milliseconds);
  return {
    signal: controller.signal,
    wait: (operation) => Promise.race([operation, deadline]),
    setBudget,
    get expired() { return expired; },
    dispose() { clearTimeout(timer); controller.abort(); },
  };
}
