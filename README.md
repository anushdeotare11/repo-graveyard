# 🪦 Repo Graveyard

> **"Ghost in the Machine" Hackathon Project**  
> A 100% local, air-gapped forensic inspection tool that scans your folders for abandoned Git repositories and resurrects them into an atmospheric, dark-humored virtual graveyard.

---

## 📸 Preview

<!-- SCREENSHOT_PLACEHOLDER: Replace the preview block below with your actual screenshot image (e.g. ![Repo Graveyard Screenshot](docs/screenshot.png)) -->
```
+-----------------------------------------------------------------------------------+
|  🕯️  REPO GRAVEYARD                 [100% Local & Private] [🟢 Gemma 3:4b Ready]  |
|  Where dead code rests, unresolved TODOs haunt, and local spirits speak.          |
+-----------------------------------------------------------------------------------+
|  [ C:\Projects                            ]  [ Scan Projects ]  [ 🔮 Séance ]    |
+-----------------------------------------------------------------------------------+
|  🌱 Still Among the Living (Recent commits detected)                             |
|  [● spectral-cli  4d ago]  [● pixel-roguelike-core  75d ago]                      |
+-----------------------------------------------------------------------------------+
|  ⚰️ The Cemetery Grounds                                                          |
|                                                                                   |
|    +-------------------+    +-------------------+    +-------------------+        |
|   /       R.I.P.        \   |      R.I.P.       |   ✝       R.I.P.        |       |
|  |   neural-toaster      |  | crypto-tamagotchi |  | vim-exit-simulator   |       |
|  |    2021 — 2022        |  |    2022 — 2023    |  |    2023 — 2023        |       |
|  | [ABANDONED MID-SENT]  |  |  [SUDDEN DEATH]   |  |  [SUDDEN DEATH]       |       |
|  | "Burnt to a crisp     |  | "Starved to death |  | "Trapped between :q!  |       |
|  |  after 68 commits..." |  |  after gas fees." |  |  and :wq forever..."  |       |
|  +-----------------------+  +-------------------+  +-----------------------+      |
+-----------------------------------------------------------------------------------+
```

---

## ⚡ What It Is

Repo Graveyard analyzes your local project directories, reads pure Git history with zero external telemetry, and visualizes abandoned projects through a rich nighttime necropolis:

- **Deterministic Cause of Death**: Rule-based diagnosis grounded in Git metrics:
  - *"Abandoned mid-sentence"* (last commit message contains `wip`, `todo`, `fix later`, `temp`)
  - *"Died young"* (< 10 total commits)
  - *"Death by TODO"* ($\ge 10$ unresolved TODO/FIXME/HACK items in tracked text files)
  - *"Sudden death"* ($\ge 20$ commits followed by $\ge 180$ days of complete silence)
  - *"Fizzled out"* (gradual slowdown into the void)
- **Local AI Eulogies (Gemma 3:4b)**: Generates 1–2 line custom tombstone epitaphs in a background queue.
- **Lazy Ghost Stories via SSE**: Clicking a tombstone streams an ~80-word first-person monologue from the repo's ghost, strictly grounded in commit logs, unresolved TODOs, and README goals.
- **Séance (Resurrection Plan)**: Identifies the project with the highest revival score and streams a concrete 3-step resurrection plan using only the README first lines, TODO lines, and last 5 commit messages.
- **Zero-Dependency Standalone Export**: Generates a self-contained offline `.html` file with embedded data, custom CSS, and optional repo name redaction.

---

## 🚀 Quick Setup

### 1. Prerequisites
- **Python 3.9+**
- **Git** CLI installed and available in PATH
- *(Optional but recommended for AI features)*: **[Ollama](https://ollama.com)**

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Setup Local AI (Ollama)
```bash
# 1. Start Ollama (if not already running as a daemon)
ollama serve

# 2. Pull the Gemma 3 4B model
ollama pull gemma3:4b
```
*(Note: If Ollama is not installed or offline, Repo Graveyard seamlessly falls back to deterministic historical narratives and rules—nothing crashes!)*

### 4. Run Repo Graveyard
- **Windows**: Double-click `run.bat` or run:
  ```cmd
  python run.py
  ```
- **macOS / Linux**:
  ```bash
  chmod +x run.sh
  ./run.sh
  ```

Open your browser to: **[http://127.0.0.1:8000](http://127.0.0.1:8000)**

---

## 🛡️ Why Open Source / Local Matters Here

1. **100% Offline & Air-Gapped**: Repo Graveyard makes zero network requests to external servers, CDNs, or third-party fonts. The CSS and JavaScript are strictly vanilla and served locally.
2. **Private Source Code Never Leaves Your Machine**: Software history holds confidential company IP, proprietary architecture, internal commit messages, unredacted secrets, and private TODOs. By running local models with Ollama, your codebase telemetry stays safely on local silicon.
3. **Model Swappable with a Single Config Line**: Swap out models by changing a single parameter in `app/config.py` or setting an environment variable:
   ```python
   # In app/config.py
   OLLAMA_MODEL = os.getenv("REPO_GRAVEYARD_MODEL", "gemma3:4b")
   ```
   Drop in `gemma3:12b`, `mistral`, `phi3`, or your custom fine-tune without changing application code.
4. **Standalone Portability (No SaaS Lock-in)**: The **Export Graveyard** feature generates a plain, single `.html` snapshot with inline CSS/JS and embedded JSON. It can be archived to a thumb drive, sent via email, or hosted on internal air-gapped documentation servers without any subscription or proprietary viewer.

---

## 📂 Project Structure

```
repo-graveyard/
├── app/
│   ├── config.py         # Single config source for thresholds, models & limits
│   ├── scanner.py        # Subprocess Git facts extractor & cause-of-death rules
│   ├── demo_data.py      # ~10 fictional repos for pitch demos & screenshots
│   ├── llm.py            # Ollama SSE client, length validator & retry engine
│   └── main.py           # FastAPI endpoints (/api/scan, /api/graveyard, /api/resurrect)
├── static/
│   ├── index.html        # Night sky backdrop, tombstones & modals
│   ├── style.css         # Pure CSS: fog, moon, lanterns, gothic tombstones
│   └── app.js            # Vanilla controller, SSE streaming & client cache
├── data/                 # JSON caches (repos, epitaphs, stories) [gitignored]
├── run.py                # Python launch script with Ollama status check
├── run.bat / run.sh      # Native desktop one-click launch scripts
├── requirements.txt      # Minimal dependencies (fastapi, uvicorn, httpx, pydantic)
└── README.md             # Documentation
```

---

## 🔧 Troubleshooting

| Symptom / Notice | Likely Cause | Fix |
| :--- | :--- | :--- |
| **"Ollama Offline (localhost:11434)"** in header badge | Ollama service is not running locally. | Open a terminal and run `ollama serve`. The app remains 100% functional with deterministic fallbacks. |
| **"Model Missing (Run: ollama pull gemma3:4b)"** | Ollama is active, but the model has not been downloaded yet. | Run `ollama pull gemma3:4b` in your terminal. |
| **Port 8000 already in use** | Another process is listening on port 8000. | Run `PORT=8080 python run.py` (or set `PORT` in your environment) or close the conflicting application. |
| **"Git not found" error during scan** | Git CLI is not installed or not in system `PATH`. | Install Git for Windows/macOS/Linux and ensure `git --version` works in your shell. |
| **Path containing spaces or backslashes** | Windows path formatting. | Enter paths as `C:\Projects\My Folder` or `C:/Projects/My Folder` directly into the scan bar. Quotes are not needed. |
| **Resetting or Clearing Old Scan Data** | Cached results in `./data/`. | Simply delete files inside the `./data/` folder (or re-scan any directory); `.data/` is excluded from git tracking. |

---

## 📜 License
Open source under the MIT License. Built for the **Ghost in the Machine** Hackathon.
