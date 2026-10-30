"""Main FastAPI application for Repo Graveyard."""
import asyncio
import json
import os
import re
from pathlib import Path
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import (
    BASE_DIR,
    DATA_DIR,
    REPOS_CACHE_FILE,
    EPITAPHS_CACHE_FILE,
    STORIES_CACHE_FILE,
    RESURRECT_CACHE_FILE,
    OLLAMA_MODEL,
    SCAN_MAX_DEPTH,
)
from app.scanner import scan_directory_for_repos, compute_revival_score
from app.demo_data import DEMO_REPOS
from app.llm import (
    check_ollama_status,
    generate_epitaph,
    stream_ghost_story,
    stream_resurrect_plan,
    epitaphs_cache,
    stories_cache,
    resurrect_cache,
    save_cache,
)

app = FastAPI(title="Repo Graveyard", version="1.0.0")

STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(exist_ok=True)

# Mount static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Current in-memory repos state
current_repos: List[Dict[str, Any]] = []

def init_repos():
    global current_repos
    if REPOS_CACHE_FILE.exists():
        try:
            with open(REPOS_CACHE_FILE, "r", encoding="utf-8") as f:
                current_repos = json.load(f)
        except Exception:
            current_repos = []
    if not current_repos:
        current_repos = list(DEMO_REPOS)
        # Preseed demo epitaphs and stories
        for r in DEMO_REPOS:
            rid = r.get("id")
            if r.get("epitaph") and rid not in epitaphs_cache:
                epitaphs_cache[rid] = r["epitaph"]
            if r.get("story") and rid not in stories_cache:
                stories_cache[rid] = r["story"]
        save_cache(EPITAPHS_CACHE_FILE, epitaphs_cache)
        save_cache(STORIES_CACHE_FILE, stories_cache)

init_repos()

class ScanRequest(BaseModel):
    path: str
    max_depth: Optional[int] = 4

class RedactExportRequest(BaseModel):
    redact: bool = False

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return HTMLResponse("<h1>Repo Graveyard UI Loading...</h1>")

@app.get("/api/status")
async def get_status():
    ollama_info = await check_ollama_status()
    dead_count = sum(1 for r in current_repos if r.get("status") in ["dead", "ancient"])
    living_count = sum(1 for r in current_repos if r.get("status") in ["alive", "sleeping"])
    return {
        "ollama": ollama_info,
        "active_model": OLLAMA_MODEL,
        "repo_count": len(current_repos),
        "dead_ancient_count": dead_count,
        "living_count": living_count,
        "has_cached_repos": REPOS_CACHE_FILE.exists(),
    }

class ScanPayload(BaseModel):
    path: Optional[str] = None
    root_path: Optional[str] = None
    max_depth: Optional[int] = None

@app.get("/api/graveyard")
async def get_graveyard(demo: Optional[str] = None):
    """Return cached graveyard repos or ~10 fictional repos if ?demo=1."""
    global current_repos
    is_demo = str(demo).lower() in ["1", "true", "yes"] if demo is not None else False
    if is_demo:
        current_repos = list(DEMO_REPOS)
        for r in DEMO_REPOS:
            rid = r.get("id") or r.get("name")
            if r.get("epitaph"):
                epitaphs_cache[rid] = r["epitaph"]
            if r.get("story"):
                stories_cache[rid] = r["story"]
        source_repos = [dict(r) for r in DEMO_REPOS]
    else:
        if not current_repos and REPOS_CACHE_FILE.exists():
            try:
                with open(REPOS_CACHE_FILE, "r", encoding="utf-8") as f:
                    current_repos = json.load(f)
            except Exception:
                current_repos = []
        source_repos = [dict(r) for r in current_repos]

    # Attach cached epitaphs and guarantee alias keys
    for r in source_repos:
        rid = r.get("id") or r.get("name")
        if rid in epitaphs_cache:
            r["epitaph"] = epitaphs_cache[rid]
        if "number_of_authors" not in r and "author_count" in r:
            r["number_of_authors"] = r["author_count"]
        if "author_count" not in r and "number_of_authors" in r:
            r["author_count"] = r["number_of_authors"]
        if "count_of_todos" not in r and "todo_count" in r:
            r["count_of_todos"] = r["todo_count"]
        if "todo_count" not in r and "count_of_todos" in r:
            r["todo_count"] = r["count_of_todos"]
        if "first_line_of_readme" not in r and "readme_preview" in r:
            r["first_line_of_readme"] = r["readme_preview"]
        if "readme_preview" not in r and "first_line_of_readme" in r:
            r["readme_preview"] = r["first_line_of_readme"]

    return source_repos

@app.post("/api/scan")
async def api_scan(
    payload: Optional[ScanPayload] = None,
    path: Optional[str] = None,
    root_path: Optional[str] = None,
    request: Request = None,
):
    """Scan folder for git repos up to depth 3, skipping hidden/system folders, node_modules, venvs."""
    target_str = None
    max_depth = SCAN_MAX_DEPTH

    if payload:
        target_str = payload.path or payload.root_path
        if payload.max_depth:
            max_depth = payload.max_depth
    if not target_str:
        target_str = path or root_path
    if not target_str and request:
        try:
            body = await request.json()
            if isinstance(body, dict):
                target_str = body.get("path") or body.get("root_path")
                if body.get("max_depth"):
                    max_depth = int(body.get("max_depth"))
        except Exception:
            pass
    if not target_str and request:
        try:
            form = await request.form()
            target_str = form.get("path") or form.get("root_path")
            if form.get("max_depth"):
                max_depth = int(form.get("max_depth"))
        except Exception:
            pass

    if not target_str:
        raise HTTPException(status_code=400, detail="Missing root path in scan request")

    target_path = Path(os.path.expanduser(target_str.strip()))
    if not target_path.exists() or not target_path.is_dir():
        raise HTTPException(status_code=404, detail=f"Directory does not exist: {target_str}")

    results = scan_directory_for_repos(target_path, max_depth=max_depth)

    global current_repos
    current_repos = results

    # Persist scan results as JSON in ./data
    try:
        with open(REPOS_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(current_repos, f, indent=2)
    except Exception:
        pass

    # Trigger background sequential epitaph generation (one at a time) for Dead/Ancient repos
    asyncio.create_task(_background_epitaph_queue(results))

    return results

async def _background_epitaph_queue(repos: List[Dict[str, Any]]):
    """Generate 1-2 line epitaphs one at a time in the background for Dead and Ancient repos."""
    status = await check_ollama_status()
    if not status.get("connected") or not status.get("model_available"):
        return
    targets = [
        r for r in repos
        if r.get("status") in ["dead", "ancient"] and (r.get("id") not in epitaphs_cache or not epitaphs_cache.get(r.get("id")))
    ]
    for r in targets:
        try:
            await generate_epitaph(r)
            await asyncio.sleep(0.4)
        except Exception:
            pass

@app.get("/api/repos")
async def get_repos():
    # Attach cached epitaphs to repos before returning
    for r in current_repos:
        rid = r.get("id") or r.get("name")
        if rid in epitaphs_cache:
            r["epitaph"] = epitaphs_cache[rid]
        elif not r.get("epitaph"):
            r["epitaph"] = None
    return {
        "repos": current_repos,
        "total": len(current_repos),
    }

@app.post("/api/demo")
async def load_demo():
    global current_repos
    current_repos = list(DEMO_REPOS)
    with open(REPOS_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(current_repos, f, indent=2)
    # Preload demo epitaphs and stories into cache
    for r in DEMO_REPOS:
        rid = r.get("id")
        if r.get("epitaph"):
            epitaphs_cache[rid] = r["epitaph"]
        if r.get("story"):
            stories_cache[rid] = r["story"]
    save_cache(EPITAPHS_CACHE_FILE, epitaphs_cache)
    save_cache(STORIES_CACHE_FILE, stories_cache)
    return {"message": "Demo mode loaded successfully", "count": len(current_repos)}

@app.get("/api/scan/stream")
async def scan_stream(path: str, max_depth: int = 4):
    """Server-Sent Events endpoint to stream scan progress in real-time."""
    target_path = Path(os.path.expanduser(path.strip()))
    if not target_path.exists() or not target_path.is_dir():
        async def err_gen():
            yield f"data: {json.dumps({'error': f'Directory does not exist: {path}'})}\n\n"
        return StreamingResponse(err_gen(), media_type="text/event-stream")

    async def event_generator():
        yield f"data: {json.dumps({'status': 'searching', 'message': f'Searching for git repositories in {path}...' })}\n\n"
        
        loop = asyncio.get_event_loop()
        progress_queue = asyncio.Queue()

        def on_progress(repo_name: str, current_idx: int, total: int):
            loop.call_soon_threadsafe(
                progress_queue.put_nowait,
                {"status": "analyzing", "repo_name": repo_name, "current": current_idx, "total": total}
            )

        # Run scanner in background thread to avoid blocking event loop
        scan_future = loop.run_in_executor(
            None,
            lambda: scan_directory_for_repos(target_path, max_depth=max_depth, progress_callback=on_progress)
        )

        while not scan_future.done():
            try:
                msg = await asyncio.wait_for(progress_queue.get(), timeout=0.15)
                yield f"data: {json.dumps(msg)}\n\n"
            except asyncio.TimeoutError:
                await asyncio.sleep(0.05)

        # Drain remaining progress items
        while not progress_queue.empty():
            msg = progress_queue.get_nowait()
            yield f"data: {json.dumps(msg)}\n\n"

        results = await scan_future
        global current_repos
        current_repos = results

        # Persist to cache
        try:
            with open(REPOS_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(current_repos, f, indent=2)
        except Exception:
            pass

        # Trigger background sequential epitaph generation (one at a time)
        asyncio.create_task(_background_epitaph_queue(results))

        yield f"data: {json.dumps({'status': 'complete', 'total_found': len(results), 'repos': results})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

@app.get("/api/story/{repo_id}")
async def get_story_stream(repo_id: str, refresh: bool = False):
    """Stream ghost story token-by-token using SSE."""
    repo = next((r for r in current_repos if (r.get("id") == repo_id or r.get("name") == repo_id)), None)
    if not repo:
        repo = next((r for r in DEMO_REPOS if (r.get("id") == repo_id or r.get("name") == repo_id)), None)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found in current graveyard")

    async def event_generator():
        async for chunk in stream_ghost_story(repo, force_refresh=refresh):
            yield f"data: {chunk}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

@app.post("/api/batch-epitaphs")
async def batch_generate_epitaphs(background_tasks: BackgroundTasks):
    """Trigger background generation of epitaphs for dead/ancient repos lacking one."""
    targets = [
        r for r in current_repos
        if r.get("status") in ["dead", "ancient"] and (r.get("id") not in epitaphs_cache)
    ]

    async def _worker():
        for r in targets:
            try:
                await generate_epitaph(r)
                await asyncio.sleep(0.2)
            except Exception:
                pass

    background_tasks.add_task(_worker)
    return {"queued": len(targets)}

@app.get("/api/resurrect")
async def resurrect_candidate():
    """Pick top resurrection candidate and stream a 3-step séance revival plan."""
    repos_to_check = current_repos if current_repos else DEMO_REPOS
    dead_candidates = [r for r in repos_to_check if r.get("status") in ["dead", "ancient"]]
    if not dead_candidates:
        # Fallback to any repo if no dead ones exist
        dead_candidates = repos_to_check

    if not dead_candidates:
        raise HTTPException(status_code=400, detail="Graveyard is empty. Scan repos first.")

    # Rank by revival_score descending
    top_candidate = max(dead_candidates, key=lambda r: r.get("revival_score", 0))

    async def event_generator():
        # First send candidate metadata event
        yield f"data: {json.dumps({'type': 'candidate', 'repo': top_candidate})}\n\n"
        # Then stream the revival plan tokens
        async for chunk in stream_resurrect_plan(top_candidate):
            yield f"data: {chunk}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

@app.post("/api/export")
async def export_graveyard(payload: RedactExportRequest):
    """Generate a 100% standalone single-file HTML bundle of the graveyard with embedded data."""
    redact = payload.redact
    css_content = ""
    css_path = STATIC_DIR / "style.css"
    if css_path.exists():
        with open(css_path, "r", encoding="utf-8") as f:
            css_content = f.read()

    js_content = ""
    js_path = STATIC_DIR / "app.js"
    if js_path.exists():
        with open(js_path, "r", encoding="utf-8") as f:
            js_content = f.read()

    # Repos to export
    repos_to_export = current_repos if current_repos else DEMO_REPOS

    # Clone repos and redact if requested
    export_repos = []
    for idx, r in enumerate(repos_to_export):
        clone = dict(r)
        rid = clone.get("id") or clone.get("name")
        if rid in epitaphs_cache:
            clone["epitaph"] = epitaphs_cache[rid]
        if rid in stories_cache:
            clone["story"] = stories_cache[rid]
        if redact:
            orig_name = r.get("name", "")
            orig_path = r.get("path", "")
            orig_author = r.get("last_author", "")

            clone["id"] = f"unnamed_project_{idx + 1}"
            clone["name"] = "Unnamed Project"
            clone["path"] = "/redacted/workspace/repo"
            clone["last_author"] = "Anonymous Developer"
            clone["readme_preview"] = "[Redacted project summary]"
            if clone.get("first_line_of_readme"):
                clone["first_line_of_readme"] = "[Redacted project summary]"
            if clone.get("last_commit_message"):
                clone["last_commit_message"] = "[Redacted commit message]"
            if clone.get("last_5_commits"):
                clone["last_5_commits"] = ["[Redacted commit message]"] * len(clone["last_5_commits"])
            if clone.get("todo_lines"):
                clone["todo_lines"] = ["[Redacted TODO line]"] * len(clone["todo_lines"])
            if clone.get("top_files"):
                clone["top_files"] = [f"src/module_{i+1}.ext" for i in range(len(clone["top_files"]))]

            def _scrub_text(text: str) -> str:
                if not text:
                    return ""
                s = text
                if orig_name:
                    s = re.sub(r'\b' + re.escape(orig_name) + r'\b', "Unnamed Project", s, flags=re.IGNORECASE)
                    s = re.sub(r'\b' + re.escape(orig_name.replace("-", " ")) + r'\b', "Unnamed Project", s, flags=re.IGNORECASE)
                    s = re.sub(r'\b' + re.escape(orig_name.replace("_", " ")) + r'\b', "Unnamed Project", s, flags=re.IGNORECASE)
                if orig_author and orig_author != "Unknown":
                    s = re.sub(r'\b' + re.escape(orig_author) + r'\b', "Anonymous Developer", s, flags=re.IGNORECASE)
                if orig_path:
                    s = s.replace(orig_path, "/redacted/workspace/repo")
                    s = s.replace(orig_path.replace("\\", "/"), "/redacted/workspace/repo")
                    s = s.replace(orig_path.replace("/", "\\"), "/redacted/workspace/repo")
                # Scrub absolute system paths (e.g. C:\Users\... or /home/...)
                s = re.sub(r"[A-Za-z]:\\[^ \"'<>]+", "/redacted/workspace/repo", s)
                s = re.sub(r"/(Users|home)/[^ \"'<>]+", "/redacted/workspace/repo", s)
                return s

            if clone.get("epitaph"):
                clone["epitaph"] = _scrub_text(clone["epitaph"])

            if clone.get("story"):
                clone["story"] = _scrub_text(clone["story"])

        export_repos.append(clone)

    data_json = json.dumps(export_repos, ensure_ascii=False)

    html_template = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Repo Graveyard (Exported Archive)</title>
  <style>
{css_content}
  </style>
</head>
<body class="export-mode">
  <div class="sky-background">
    <div class="stars"></div>
    <div class="moon"></div>
    <div class="fog-layer fog-back"></div>
    <div class="fog-layer fog-mid"></div>
  </div>

  <div class="graveyard-container">
    <header class="graveyard-header">
      <div class="header-title-wrap">
        <span class="header-icon">🪦</span>
        <h1>Repo Graveyard</h1>
        <span class="export-badge">Offline Archive {'(Redacted)' if redact else ''}</span>
      </div>
      <p class="header-subtitle">Honoring the abandoned projects, unresolved TODOs, and unfinished dreams of the past.</p>
    </header>

    <div class="export-notice">
      <span>🕯️ This is an exported, self-contained snapshot generated by Repo Graveyard. Works 100% offline with zero external dependencies.</span>
    </div>

    <!-- Living Strip -->
    <div id="livingStripContainer" class="living-strip-section"></div>

    <!-- Cemetery Grid grouped by Section -->
    <main id="cemeterySections" class="cemetery-sections"></main>
  </div>

  <!-- Ghost Story / Tombstone Inspection Modal -->
  <div id="tombstoneModal" class="modal-backdrop hidden" role="dialog" aria-modal="true">
    <div class="modal-card tombstone-detail-card">
      <button id="modalCloseBtn" class="modal-close" aria-label="Close dialog">&times;</button>
      
      <div class="tombstone-header-row">
        <div class="spirit-avatar-wrap">
          <div class="spirit-orb"></div>
          <span class="spirit-icon">👻</span>
        </div>
        <div class="tombstone-title-wrap">
          <h2 id="modalRepoName" class="tomb-heading">repo-name</h2>
          <div class="tombstone-meta-line">
            <span id="modalLifespan" class="meta-pill">2021 — 2023</span>
            <span id="modalCauseBadge" class="cause-badge">Abandoned mid-sentence</span>
            <span id="modalRevivalScore" class="revival-pill">Revival Score: 85</span>
          </div>
        </div>
      </div>

      <!-- Real Git Facts Grid -->
      <div class="facts-panel">
        <h4 class="panel-heading">Grounded Git Facts (From History)</h4>
        <div class="facts-grid">
          <div class="fact-item">
            <span class="fact-label">Total Commits</span>
            <span id="modalTotalCommits" class="fact-val">0</span>
          </div>
          <div class="fact-item">
            <span class="fact-label">Last Commit</span>
            <span id="modalDaysAgo" class="fact-val">0 days ago</span>
          </div>
          <div class="fact-item">
            <span class="fact-label">Last Contributor</span>
            <span id="modalLastAuthor" class="fact-val">dev</span>
          </div>
          <div class="fact-item">
            <span class="fact-label">Unfinished TODOs</span>
            <span id="modalTodoCount" class="fact-val">0</span>
          </div>
        </div>

        <div class="fact-message-box">
          <span class="fact-label">Final Commit Message</span>
          <div id="modalLastMessage" class="fact-quote">"..."</div>
        </div>

        <div class="fact-files-box">
          <span class="fact-label">Top Modified Files</span>
          <div id="modalTopFiles" class="fact-files-tags"></div>
        </div>
      </div>

      <!-- Ghost Monologue Section -->
      <div class="ghost-story-section">
        <div class="story-header-row">
          <h4 class="story-title">
            <span class="flicker-flame">🕯️</span>
            Spirit's Monologue
            <span id="storyFallbackBadge" class="story-fallback-badge hidden" title="Generated deterministically without AI model">written without the model</span>
          </h4>
        </div>
        
        <div id="ghostStoryBox" class="story-content-box">
          <div id="ghostStoryText" class="ghost-text">Summoning repository spirit...</div>
          <span id="storyStreamCursor" class="streaming-cursor hidden"></span>
        </div>
      </div>
    </div>
  </div>

  <script id="embedded-graveyard-data" type="application/json">
{data_json}
  </script>

  <script>
    // Embedded standalone reader
    const EMBEDDED_DATA = JSON.parse(document.getElementById('embedded-graveyard-data').textContent);
    window.STANDALONE_EXPORT = true;
    window.EXPORT_REPOS = EMBEDDED_DATA;
{js_content}
  </script>
</body>
</html>"""

    if redact:
        # Common generic words that must NEVER be touched in raw HTML to avoid corrupting tags, styles, or scripts
        REDACT_COMMON_WORDS = {
            "app", "test", "src", "data", "style", "main", "code", "repo", "graveyard",
            "docs", "build", "dist", "web", "site", "root", "dev", "node", "lib", "index",
            "home", "base", "user", "file", "text", "view", "core", "tool", "work", "item",
            "demo", "font", "page", "head", "body", "span", "card", "grid", "time", "date"
        }

        # Filter candidates: skip names < 4 chars or common words in raw-HTML pass
        valid_name_scrubs = []
        valid_author_scrubs = []
        path_scrubs = []

        for r in repos_to_export:
            oname = r.get("name", "")
            oauthor = r.get("last_author", "")
            opath = r.get("path", "")

            if oname and len(oname) >= 4 and oname.lower() not in REDACT_COMMON_WORDS:
                valid_name_scrubs.append(oname)
            if oauthor and oauthor != "Unknown" and len(oauthor) >= 3 and oauthor.lower() not in REDACT_COMMON_WORDS:
                valid_author_scrubs.append(oauthor)
            if opath:
                path_scrubs.append(opath)

        # Tokenize HTML so we NEVER touch <style>, <script>, or any HTML tag <...>
        # Pattern splits on <style>...</style>, <script>...</script>, or <tag ...>
        token_pattern = re.compile(r'(<style[\s\S]*?</style>|<script[\s\S]*?</script>|<[^>]+>)', re.IGNORECASE)
        parts = token_pattern.split(html_template)

        for i in range(len(parts)):
            # Even-indexed elements are pure visible text outside tags, scripts, and styles
            if i % 2 == 0 and parts[i]:
                text = parts[i]
                for name in valid_name_scrubs:
                    text = re.sub(r'\b' + re.escape(name) + r'\b', "Unnamed Project", text, flags=re.IGNORECASE)
                for author in valid_author_scrubs:
                    text = re.sub(r'\b' + re.escape(author) + r'\b', "Anonymous Developer", text, flags=re.IGNORECASE)
                for path in path_scrubs:
                    text = text.replace(path, "/redacted/workspace/repo")
                    text = text.replace(path.replace("\\", "/"), "/redacted/workspace/repo")
                    text = text.replace(path.replace("/", "\\"), "/redacted/workspace/repo")
                parts[i] = text

        html_template = "".join(parts)

    filename = "repo_graveyard_redacted.html" if redact else "repo_graveyard.html"
    return HTMLResponse(
        content=html_template,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )
