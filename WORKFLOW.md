# Closed-End Dataset & DuckDB Profiling Workflow Architecture

This document details the end-to-end operational workflow of the **Offline AI Data Analyst** system following the transition to a closed-ended, pre-loaded dataset catalog with DuckDB SQL profiling.

---

## Workflow Overview Diagram

```
+-----------------------------------------------------------------------------------+
| 1. DEVELOPER / OPERATOR                                                           |
|    Places CSV / JSON / Excel files into the root `datasets/` directory.           |
+-----------------------------------------------------------------------------------+
                                        |
                                        v
+-----------------------------------------------------------------------------------+
| 2. APPLICATION STARTUP (main.py -> MetadataService.scan_and_profile_catalog())     |
|    a. Scans `datasets/` directory for files.                                      |
|    b. Compares size_bytes & mtime against cached `profile_[dataset_id].json`.    |
|    c. Runs DuckDB `SUMMARIZE` query on missing/modified datasets.                 |
|    d. Caches profile JSON under `workspace/catalog_metadata/`.                    |
|    e. Logs summary: Newly Profiled, Skipped, Re-Profiled, Orphaned.               |
+-----------------------------------------------------------------------------------+
                                        |
                                        v
+-----------------------------------------------------------------------------------+
| 3. CLIENT USER INTERFACE (React / Vite)                                           |
|    a. Fetch catalog list via GET `/api/v1/datasets/catalog`.                     |
|    b. Render pre-loaded dataset items in Sidebar catalog panel.                  |
|    c. User selects dataset -> fetch GET `/api/v1/datasets/{id}/preview` &        |
|       `/profile` (Reads PRE-COMPUTED cache, zero on-demand profiling).            |
+-----------------------------------------------------------------------------------+
                                        |
                                        v
+-----------------------------------------------------------------------------------+
| 4. CHAT QUERY & ANALYSIS EXECUTION (POST `/api/v1/chat/message`)                   |
|    a. Retrieve pre-cached dataset schema profile JSON.                            |
|    b. LLM QueryPlanner classifies intent (SIMPLE vs COMPLEX vs CONVERSATION).     |
|    c. SIMPLE: Deterministic pandas/DuckDB execution via AnalysisEngine.           |
|    d. COMPLEX: CodeGenerator creates Python code; SandboxRunner executes code inside|
|       isolated subprocess with AST security checks and 2GB / 10s memory bounds.  |
|    e. ResultInterpreter formats response text and returns base64 chart / table.   |
+-----------------------------------------------------------------------------------+
```

---

## Detailed Step-by-Step Workflow

### Step 1: Catalog Dataset Management (Developer/Operator)
- All dataset files (CSV, JSON, XLSX) are manually placed in the project root directory: `datasets/`.
- No user upload forms or client-side upload API endpoints exist (`POST /upload` has been removed).

### Step 2: Automatic Startup Scanning & DuckDB Profiling
When the FastAPI backend boots up (`main.py` -> `@app.on_event("startup")`):
1. **Directory Discovery**: `MetadataService.scan_and_profile_catalog()` scans `datasets/`.
2. **Cache Verification**: For each file, `MetadataService` checks `workspace/catalog_metadata/profile_[dataset_id].json`:
   - If missing: Generate profile.
   - If size or modification timestamp (`mtime`) changed: Re-generate profile.
   - If unchanged: Skip (load instantly from cache).
3. **DuckDB SQL Profiling Engine**:
   - Executes `SUMMARIZE SELECT * FROM read_csv_auto('<file>.csv')` directly in DuckDB (in-memory, no pandas/numpy memory bloat).
   - Generates numeric stats (`mean`, `std`, `min`, `max`, `q25`, `q50`, `q75`).
   - Runs top-N frequency query for categorical fields capped at 15 items.
   - Detects **identifier-like columns** (`unique_values / total_rows > 0.90`).
   - Flags missing values and invalid calculations cleanly.
4. **Summary Logging**: Logs report of `Newly Profiled`, `Skipped (Unchanged)`, `Re-Profiled (Changed)`, and `Orphaned Profiles`.

### Step 3: Frontend Catalog Interaction
1. Upon loading, the React app invokes `loadCatalogDatasets()` via `GET /api/v1/datasets/catalog`.
2. The UI renders the fixed dataset catalog in `Sidebar.jsx`.
3. Selecting a dataset calls `GET /api/v1/datasets/{dataset_id}/preview` and `GET /api/v1/datasets/{dataset_id}/profile`.
4. **Zero On-Demand Work**: The backend simply reads the pre-computed profile JSON created during startup.

### Step 4: Security-Bounded Natural Language Querying
When the user sends a message in the chat:
1. `chat.py` fetches the pre-cached metadata profile.
2. `QueryPlanner` sends the schema + prompt to local Ollama (`qwen2.5-coder`) to determine query intent.
3. For Python code generation (`COMPLEX` intent):
   - Code is scanned by `ASTScanner` for dangerous calls (`os`, `sys`, `subprocess`, `open`).
   - Executed inside a resource-bounded Python subprocess (`SandboxRunner`) enforcing 2GB virtual memory ceiling and 10.0-second execution timeout.
   - Plotly/Matplotlib charts and Pandas outputs are captured and returned to the React frontend.
