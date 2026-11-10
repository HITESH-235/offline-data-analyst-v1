# V1 request deadline — 2026-11-09

The Olist request `c0bc55bf-b523-4b57-8aba-60a7e2055314` finished at 15:24:42.976700 UTC, about 565.6 seconds after submission. The planner started at 15:15:17.422 and returned at 15:24:41.116 (563.694 seconds). The observed delay was inside the planner provider call. Available evidence cannot distinguish provider computation from waiting for response headers/body. Backend health checks stayed responsive. Older schema-repair failures were separate requests.

The final response `25459fca-ea29-4a0b-b82a-a7624d00a8b1` returned 27 state late-order counts, sorted by count. It did **not** answer the requested comparable counts and late percentages or percentage sorting. `comparison_summary` has no `group_by`; separate aggregation outputs do not establish a verified grouped ratio. This remains a tool/planning support gap. No grouped percentage implementation or replacement calculation was added in this deadline task. The previous verified overall result (`1534a760-4483-4269-bfb2-85e8185e8276`) remains in the database: 96,470 comparable orders, 6,534 late, 6.773090%.

Before Python edits/reload, the original request/process evidence, planner diagnostics, and project messages were copied to `workspace/evaluations/request-deadline-2026-11-09/`. The original request had already finished; no duplicate submission or live model request was made. Existing datasets, saved results, themes and unrelated uncommitted changes were preserved.

## Behavior and configuration

- `CHAT_REQUEST_TIMEOUT_SECONDS` defaults to **120**, accepts positive values up to 3600, and is passed through Compose. It is one monotonic budget for validation, planning, the optional single schema repair, selection, execution, finalization and publication. Changing Compose environment requires container recreation using the existing provider environment configuration; do not replace that configuration.
- Both HTTP routes share a supervisor. JSON returns HTTP **504** with `analysis_status: "timed_out"`; NDJSON emits a terminal `timed_out` event and closes. Neither waits for worker termination at timeout.
- Each worker owns its SQLAlchemy session. Direct synchronous `process_chat_message` callers remain compatible; direct endpoint tests now await the async route and provide a worker-compatible session factory.
- Client disconnect cancels the request. JSON polls disconnect state; streaming uses StreamingResponse iterator cancellation. Cancellation closes established provider sockets, kills the sandbox subprocess, and checks before later stages/model turns/tool iterations/publication.
- Provider socket waits are clamped to the remaining request budget. Socket shutdown also interrupts waiting for headers or an incomplete body. The supervisor handles bodies that continually dribble data past socket inactivity limits.
- Publication is fenced against timeout/cancellation. Slow DB insertion happens before the short commit fence, with an uncommitted transaction rolled back if cancellation wins. Successful analysis history is not replaced by a timeout. Timeout state is retained in per-request diagnostics and the current UI reply; no successful assistant result is inserted for a timed-out request.
- Frontend watchdog covers both fetch and stream reads, aborts the transport and clears pending state. With response headers it uses the advertised backend budget plus 5 seconds; without headers it defaults to **135 seconds**, configurable with `VITE_CHAT_REQUEST_TIMEOUT_SECONDS`. CORS exposes the budget header. Late network resolutions cannot update the reply after the watchdog has won.
- Request diagnostics are written under `workspace/evaluations/request-deadlines/<request-id>.json`: terminal status, stage UTC/elapsed timestamps, model-call counts/durations, and the planner's existing sanitized diagnostics. Provider headers, keys and full prompts are not added. Normal saved replies include the request ID.
- Planner repair limits and existing calculation/population/formula/source/unit/completion checks were retained.

Cancellation limits: Python cannot safely kill a running worker thread. In-process dataframe/native computations and DNS/connect/TLS setup before socket registration can continue until their own operation returns or times out; cooperative guards prevent subsequent work and result publication. Closing a provider connection does not prove the remote provider stopped computing. Chart file copies can finish before the next cancellation check, but a cancelled request cannot publish a new chart manifest or assistant result after its publication fence closes. Database commit and manifest writes are short serialized publication steps; this is an application deadline, not a hard real-time scheduler guarantee.

## Validation

All checks passed:

- Full backend replay: **150 tests** (258.629 seconds), with external calls blocked. Final targeted reruns cover the subsequent publication refinement and two added cases.
- Final deadline tests: **8**, covering bounded JSON/stream timeouts, slow finalization, late-result fencing, prior-context preservation, disconnect cancellation, shared original/repair budget, socket interruption before headers/during body, sandbox kill and normal success.
- Final model-failure/call-count tests: **9**; date/revenue tests: **16**; chart artifact tests: **5**.
- Frontend test runner: **6 files** passed, including watchdog expiry/abort and normal cleanup. Production Vite build passed in the frontend container.
- Python compilation and `git diff --check` passed. Reloaded backend health returned HTTP 200; both chat routes remain registered.
- The Olist project database messages match the pre-edit evidence snapshot exactly. No commit, push, browser testing, or live model request was performed.

Logs are under `workspace/evaluations/request-deadline-2026-11-09/`.

## Browser checks (left to the user)

1. Open the V1 frontend at `http://localhost:3001`. Confirm a saved successful Olist analysis still opens with its original counts, percentage and saved result.
2. To exercise a stalled stream **without a model request**, run this in DevTools Console:

   ```js
   window.deadlineOriginalFetch = window.fetch;
   window.fetch = (input, options) => {
     if (String(input).includes('/chat/message/stream')) {
       return Promise.resolve(new Response(new ReadableStream({ start() {} }), {
         headers: { 'Content-Type': 'application/x-ndjson', 'X-Request-Timeout-Seconds': '2' }
       }));
     }
     return window.deadlineOriginalFetch(input, options);
   };
   ```

3. Send a test chat message. After approximately **7 seconds**, verify the reply says the deadline was reached, displays **Timed out**, stops spinning, and permits another send. Switching projects and returning must not leave that reply pending. There should be no new saved analysis.
4. Restore transport with `window.fetch = window.deadlineOriginalFetch; delete window.deadlineOriginalFetch;` and reload to discard the locally simulated messages.
5. To test stalled response headers, repeat the interception but return `new Promise(() => {})` for the chat URL. The reply must leave pending state at the frontend fallback budget (135 seconds by default). Restore fetch and reload afterward.
6. To check server-event rendering without a model call, intercept the chat URL with a Response containing a single JSON line:

   ```js
   JSON.stringify({stage: 'timed_out', result: {analysis_status: 'timed_out', content: 'The analysis reached its request deadline. No result was published. Please try again.'}}) + '\n'
   ```

   Send a message and confirm it immediately becomes **Timed out**. Restore fetch and reload. Actual server timeout, socket interruption, sandbox kill, and late-publication behavior are covered by the controlled backend tests.
