# Offline AI Data Analyst (V1)

An offline, self-contained AI Data Analyst application. The system allows users to upload datasets (CSV, Excel, JSON), automatically profiles them, accepts natural language queries, executes analysis within a secure Python sandbox, renders interactive visual charts, and compiles executive PDF/Markdown reports.

It is designed to run 100% offline, leveraging local LLMs (Qwen 2.5 Coder) accelerated via hardware-passthrough Docker containers on Intel Core Ultra / Arc GPUs.

---

## Key Features

*   **Offline LLM Execution**: Uses a local Ollama service running the `qwen2.5-coder:latest` (7.6B) model.
*   **Decoupled Workspaces**: User files, database states, chat history, and reports are isolated inside a dedicated `workspace/` folder completely separate from the application source code.
*   **Dual-Route Analysis Engine**:
    *   **Simple Intent**: Converts natural language requests into deterministic pandas/numpy aggregates, descriptive statistics, and correlation matrices.
    *   **Complex Intent**: Generates custom Python code, scans the AST for security violations, and executes it in a resource-bounded subprocess sandbox.
*   **Secure Execution Sandbox**: Intercepts blacklisted APIs (`os`, `sys`, `subprocess`, `open`, etc.) and enforces a 2GB virtual memory ceiling and 10.0-second execution timeout.
*   **Interactive Visualizations**: Captures plotting outputs and generates self-contained, offline-compatible Plotly HTML visualizers.
*   **Executive Reporting**: Compiles session summaries and exports them as styled PDFs and Markdown.
*   **Modern Glassmorphism UI**: Built with React (Vite) featuring a dark-mode 3-panel dashboard.

---

## Directory Structure

```text
offline-data-analyst/
├── client/                     # Frontend Code (React / Vite)
│   ├── src/
│   │   ├── components/         # UI Elements (Sidebar, Chat, Tables)
│   │   ├── context/            # React Global State Manager (Context API)
│   │   ├── index.css           # Styling system (Dark Mode & Glassmorphism)
│   │   └── main.jsx            # Entry point that mounts the app
│   └── package.json            # React dependencies
│
├── server/                     # Backend Code (FastAPI / Python)
│   ├── app/
│   │   ├── api/v1/             # API Endpoints (Chat, Datasets, Projects, Reports)
│   │   ├── core/               # Global configs and limits constants
│   │   ├── models/             # Database tables (SQLAlchemy models)
│   │   ├── services/           # Disk, Profiler, and PDF compile routines
│   │   ├── sandbox/            # AST Scanner and Python Subprocess Runner
│   │   ├── analysis/           # Clean, Filter, Aggregate math modules
│   │   └── llm/                # Ollama Client, routing prompts, and planner
│   ├── main.py                 # FastAPI Bootloader
│   └── requirements.txt        # Python backend dependencies
│
└── workspace/                  # RUNTIME DATA (100% Decoupled from code)
    ├── metadata.db             # Central SQLite Database (Project registry)
    └── projects/               # Isolated Project Folders
        └── [Project-Name]/     
            ├── data/           # Original CSV/Excel files
            ├── chat/           # Chat history JSON files
            ├── charts/         # Standalone HTML graphs
            ├── reports/        # Executive Markdown and PDF files
            └── metadata/       # Cached columns profiles
```

---

## Prerequisites

*   Linux (Arch Linux / Ubuntu)
*   Python 3.10+
*   Node.js 18+ & npm
*   Docker (for GPU acceleration)

---

## Setup & Installation

### 1. Install & Configure Docker (Intel GPU Acceleration)
To offload LLM calculations from your CPU to the Intel Arc GPU, run the following setup steps in your host terminal:

```bash
# 1. Install Docker and enable the daemon
sudo pacman -S --noconfirm docker
sudo systemctl enable --now docker

# 2. Add your user to graphics and docker permission groups
sudo usermod -aG docker,video,render $USER
```
*Note: Log out and log back in to apply group changes, or prefix docker commands with `sudo`.*

### 2. Run the Intel GPU-Optimized Ollama Container
Stop any host-level Ollama services binding to port 11434, then spin up the container:

```bash
# Stop host service if active
sudo systemctl stop ollama

# Start container with GPU direct rendering device mapping
sudo docker run -d \
  --name ollama-intel \
  --device /dev/dri:/dev/dri \
  -v ollama:/root/.ollama \
  -p 11434:11434 \
  spaceinvaderone/ollama-intel-gpu
```

### 3. Download the Qwen Coder Model
Pull the model inside the container to verify it is compiled for GPU inference:

```bash
sudo docker exec -it ollama-intel /ollama pull qwen2.5-coder:latest
```

---

## Running the Application

Open separate terminals for each component:

### 1. Start the Docker Container
```bash
sudo docker start ollama-intel
```

### 2. Start the FastAPI Backend
```bash
cd server
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

### 3. Start the React Frontend
```bash
cd client
npm install
npm run dev
```
Open your browser and navigate to `http://localhost:5173`.

---

## Testing the Pipeline

Upload a dataset and use the following queries to test each execution path:

### 1. Simple Aggregations & Grouping Path
> *"What is the average market value and average age of players grouped by their position, sorted by average market value in descending order?"*
*Checks: Mappings, aggregation logic, sort parameters, and list/dict schema normalization.*

### 2. Descriptive Statistics & Correlations
> *"Show me the descriptive statistical summary and outliers for stamina_score, player_rating, and top_speed_kmh."*
*Checks: Descriptive math engines and inter-quartile range (IQR) outlier captures.*

### 3. Sandboxed Code Execution
> *"Create a new variable for Goal Contribution per Minute (goals + assists divided by minutes_played), and print the top 5 players with their rating."*
*Checks: LLM Python generator, AST security validator blockers, and process runner execution limits.*

### 4. Interactive Plotting
> *"Generate a Seaborn density scatter plot comparing expected_goals_xg on the x-axis and goals on the y-axis, color-coded by position."*
*Checks: Matplotlib/Seaborn sandbox plotting, base64 compilation, and UI chart rendering.*
