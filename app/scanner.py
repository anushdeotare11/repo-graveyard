"""Git repository scanner and deterministic facts extractor."""
import os
import subprocess
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable

from app.config import (
    ALIVE_DAYS_THRESHOLD,
    SLEEPING_DAYS_THRESHOLD,
    DEAD_DAYS_THRESHOLD,
    SCAN_MAX_DEPTH,
    SCAN_REPO_TIMEOUT,
    IGNORED_DIRS,
)

def run_git(args: List[str], cwd: Path, timeout: int = SCAN_REPO_TIMEOUT) -> str:
    """Run a git command in the target directory and return stdout safely."""
    try:
        proc = subprocess.run(
            ["git"] + args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
    except Exception:
        pass
    return ""

def get_readme_first_line(repo_path: Path) -> str:
    """Find README file in repo root and return its first meaningful title or line."""
    for filename in ["README.md", "README", "readme.md", "Readme.md", "README.rst", "README.txt"]:
        fpath = repo_path / filename
        if fpath.is_file():
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            # Strip markdown headers like # or ##
                            clean = re.sub(r"^#+\s*", "", line)
                            if len(clean) > 3:
                                return clean[:140]
            except Exception:
                pass
    return ""

def count_todos_in_tracked_files(repo_path: Path, max_files: int = 150) -> int:
    """Count TODO/FIXME/HACK in tracked text files without reading binaries or huge files."""
    # Fast approach: use git grep if possible
    grep_out = run_git(["grep", "-i", "-E", "-c", "TODO|FIXME|HACK", "HEAD"], repo_path, timeout=5)
    if grep_out:
        total = 0
        for line in grep_out.splitlines():
            parts = line.strip().rsplit(":", 1)
            if len(parts) == 2 and parts[1].isdigit():
                total += int(parts[1])
        return total

    # Fallback: inspect tracked files
    files_out = run_git(["ls-files"], repo_path, timeout=4)
    if not files_out:
        return 0

    count = 0
    text_extensions = {
        ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".go", ".rs",
        ".c", ".cpp", ".h", ".java", ".rb", ".php", ".sh", ".md", ".json", ".yaml", ".yml"
    }

    files = [f for f in files_out.splitlines() if any(f.endswith(ext) for ext in text_extensions)]
    for rel_path in files[:max_files]:
        full_path = repo_path / rel_path
        if full_path.is_file() and full_path.stat().st_size < 300_000:
            try:
                with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        if re.search(r"\b(TODO|FIXME|HACK)\b", line, re.IGNORECASE):
                            count += 1
            except Exception:
                continue
    return count

def get_todo_lines(repo_path: Path, max_lines: int = 5) -> List[str]:
    """Retrieve actual TODO/FIXME/HACK text lines from tracked files."""
    grep_lines = run_git(["grep", "-i", "-n", "-E", "TODO|FIXME|HACK", "HEAD"], repo_path, timeout=5)
    if grep_lines:
        lines = []
        for line in grep_lines.splitlines()[:max_lines]:
            parts = line.split(":", 3)
            clean = parts[-1].strip() if parts else line.strip()
            if len(clean) > 4:
                lines.append(clean[:120])
        if lines:
            return lines

    files_out = run_git(["ls-files"], repo_path, timeout=4)
    if not files_out:
        return []
    lines = []
    text_extensions = {".py", ".js", ".ts", ".html", ".css", ".go", ".rs", ".md", ".json"}
    for rel in files_out.splitlines()[:50]:
        if any(rel.endswith(ext) for ext in text_extensions):
            fpath = repo_path / rel
            if fpath.is_file() and fpath.stat().st_size < 200_000:
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        for l in f:
                            if re.search(r"\b(TODO|FIXME|HACK)\b", l, re.IGNORECASE):
                                clean = l.strip()
                                if len(clean) > 4 and clean not in lines:
                                    lines.append(clean[:120])
                                    if len(lines) >= max_lines:
                                        return lines
                except Exception:
                    pass
    return lines

def get_top_changed_files(repo_path: Path) -> List[str]:
    """Return top 3 most frequently touched files in git history."""
    out = run_git(["log", "--name-only", "--pretty=format:", "-n", "100"], repo_path, timeout=5)
    if not out:
        return []
    file_counts: Dict[str, int] = {}
    for line in out.splitlines():
        line = line.strip()
        if line and not any(p in line for p in ["package-lock", "yarn.lock", "cargo.lock", "node_modules"]):
            file_counts[line] = file_counts.get(line, 0) + 1
    sorted_files = sorted(file_counts.items(), key=lambda x: x[1], reverse=True)
    return [item[0] for item in sorted_files[:3]]

def determine_cause_of_death(
    last_message: str,
    total_commits: int,
    days_since_last: int,
    todo_count: int,
    author_count: int = 1,
    span_days: int = 1,
) -> str:
    """Determine a rule-based cause of death based strictly on git metrics."""
    msg_lower = (last_message or "").lower()

    # Rule 1: Abandoned mid-sentence (last message has wip/fix later/todo)
    wip_triggers = ["wip", "fix later", "todo", "fixme", "temp", "tmp", "checkpoint", "halfway"]
    if any(trigger in msg_lower for trigger in wip_triggers):
        return "Abandoned mid-sentence"

    # Rule 2: Died young (<10 commits)
    if total_commits < 10:
        return "Died young"

    # Rule 3: Death by TODO (many TODOs, >= 10)
    if todo_count >= 10:
        return "Death by TODO"

    # Rule 4: Sudden death (heavy activity then nothing)
    if total_commits >= 20 and days_since_last >= 180:
        return "Sudden death"

    # Rule 5: Else Fizzled out
    return "Fizzled out"

def compute_revival_score(
    total_commits: int,
    days_since_last: int,
    has_readme: bool,
    todo_count: int,
    author_count: int,
) -> int:
    """Calculate revival potential score (0 to 100) using deterministic heuristics."""
    score = 0.0

    # 1. Total commits investment (up to 35 pts)
    # 10 commits -> ~15 pts, 50 commits -> ~28 pts, 100+ commits -> 35 pts
    if total_commits >= 100:
        score += 35
    elif total_commits >= 40:
        score += 28
    elif total_commits >= 15:
        score += 20
    elif total_commits >= 5:
        score += 10
    else:
        score += 5

    # 2. Recency (fresher dead projects are much easier to revive) (up to 25 pts)
    # 180 - 365 days: 25 pts
    # 365 - 730 days: 16 pts
    # > 730 days: 8 pts
    if days_since_last <= 365:
        score += 25
    elif days_since_last <= 730:
        score += 16
    else:
        score += 8

    # 3. README documentation presence (15 pts)
    if has_readme:
        score += 15

    # 4. Actionable TODOs (15 pts)
    # A few clear TODOs (1 to 10) give direction for revival. Zero or > 30 is worse.
    if 1 <= todo_count <= 8:
        score += 15
    elif 9 <= todo_count <= 20:
        score += 10
    elif todo_count == 0:
        score += 5
    else: # Overwhelmed by TODOs
        score += 2

    # 5. Author count investment (10 pts)
    if author_count > 1:
        score += 10
    else:
        score += 6

    return min(100, int(round(score)))

def extract_repo_facts(repo_path: Path) -> Optional[Dict[str, Any]]:
    """Inspect git repository at path and compute complete metadata."""
    if not (repo_path / ".git").exists():
        return None

    # Verify git repo is readable
    rev_count = run_git(["rev-list", "--count", "HEAD"], repo_path, timeout=5)
    if not rev_count or not rev_count.isdigit():
        # Check if this is a git repo with zero commits (unborn HEAD)
        is_git = run_git(["rev-parse", "--is-inside-work-tree"], repo_path, timeout=5)
        if is_git == "true":
            # Repository exists but has 0 commits
            clean_name = repo_path.name
            now_ts = int(datetime.now(timezone.utc).timestamp())
            git_dir = repo_path / ".git"
            last_ts = int(git_dir.stat().st_mtime) if git_dir.exists() else now_ts
            first_ts = last_ts
            first_dt = datetime.fromtimestamp(first_ts, tz=timezone.utc)
            last_dt = datetime.fromtimestamp(last_ts, tz=timezone.utc)
            days_since_last = max(0, int((now_ts - last_ts) / 86400))
            readme_line = get_readme_first_line(repo_path)
            repo_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", clean_name).lower() + f"_{abs(hash(str(repo_path.resolve()))) % 10000}"
            status = "dead" if days_since_last > 14 else "sleeping"
            return {
                "id": repo_id,
                "name": clean_name,
                "path": str(repo_path.resolve()),
                "status": status,
                "days_since_last_commit": days_since_last,
                "first_commit_date": first_dt.strftime("%Y-%m-%d"),
                "last_commit_date": last_dt.strftime("%Y-%m-%d"),
                "birth_year": first_dt.year,
                "death_year": last_dt.year,
                "total_commits": 0,
                "author_count": 1,
                "number_of_authors": 1,
                "last_commit_message": "(No commits yet)",
                "last_author": "Unknown",
                "top_files": [],
                "readme_preview": readme_line,
                "first_line_of_readme": readme_line,
                "todo_count": 0,
                "count_of_todos": 0,
                "cause_of_death": "Died before first commit",
                "revival_score": 25,
                "last_5_commits": ["(No commits yet)"],
                "todo_lines": [],
                "epitaph": f"Here rests {clean_name}. Abandoned before its first commit.",
            }
        return None

    total_commits = int(rev_count)
    if total_commits == 0:
        clean_name = repo_path.name
        now_ts = int(datetime.now(timezone.utc).timestamp())
        repo_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", clean_name).lower() + f"_{abs(hash(str(repo_path.resolve()))) % 10000}"
        return {
            "id": repo_id,
            "name": clean_name,
            "path": str(repo_path.resolve()),
            "status": "dead",
            "days_since_last_commit": 0,
            "first_commit_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "last_commit_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "birth_year": datetime.now(timezone.utc).year,
            "death_year": datetime.now(timezone.utc).year,
            "total_commits": 0,
            "author_count": 1,
            "number_of_authors": 1,
            "last_commit_message": "(No commits yet)",
            "last_author": "Unknown",
            "top_files": [],
            "readme_preview": "",
            "first_line_of_readme": "",
            "todo_count": 0,
            "count_of_todos": 0,
            "cause_of_death": "Died before first commit",
            "revival_score": 25,
            "last_5_commits": ["(No commits yet)"],
            "todo_lines": [],
            "epitaph": f"Here rests {clean_name}. Abandoned before its first commit.",
        }

    # Last commit details: unix_time|author|subject
    last_log = run_git(["log", "-1", "--format=%ct|%an|%s"], repo_path, timeout=5)
    if not last_log or "|" not in last_log:
        return None

    parts = last_log.split("|", 2)
    last_ts = int(parts[0]) if parts[0].isdigit() else int(datetime.now(timezone.utc).timestamp())
    last_author = parts[1] if len(parts) > 1 else "Unknown"
    last_message = parts[2] if len(parts) > 2 else "Initial commit"

    # First commit timestamp
    first_log = run_git(["log", "--reverse", "--format=%ct", "-1"], repo_path, timeout=5)
    first_ts = int(first_log) if first_log and first_log.isdigit() else last_ts

    now_ts = int(datetime.now(timezone.utc).timestamp())
    days_since_last = max(0, int((now_ts - last_ts) / 86400))
    span_days = max(1, int((last_ts - first_ts) / 86400))

    first_dt = datetime.fromtimestamp(first_ts, tz=timezone.utc)
    last_dt = datetime.fromtimestamp(last_ts, tz=timezone.utc)

    # Number of authors
    authors_out = run_git(["log", "--format=%an"], repo_path, timeout=5)
    author_list = set(a.strip() for a in authors_out.splitlines() if a.strip()) if authors_out else {last_author}
    author_count = max(1, len(author_list))

    # README preview
    readme_line = get_readme_first_line(repo_path)

    # TODO count
    todo_count = count_todos_in_tracked_files(repo_path)

    # Top 3 changed files
    top_files = get_top_changed_files(repo_path)

    # Deterministic status classification
    if days_since_last < ALIVE_DAYS_THRESHOLD:
        status = "alive"
    elif days_since_last <= SLEEPING_DAYS_THRESHOLD:
        status = "sleeping"
    elif days_since_last <= DEAD_DAYS_THRESHOLD:
        status = "dead"
    else:
        status = "ancient"

    # Cause of death
    cause_of_death = determine_cause_of_death(
        last_message=last_message,
        total_commits=total_commits,
        days_since_last=days_since_last,
        todo_count=todo_count,
        author_count=author_count,
        span_days=span_days,
    )

    # Revival score
    revival_score = compute_revival_score(
        total_commits=total_commits,
        days_since_last=days_since_last,
        has_readme=bool(readme_line),
        todo_count=todo_count,
        author_count=author_count,
    )

    # Unique ID based on folder path hash or slug
    clean_name = repo_path.name
    repo_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", clean_name).lower() + f"_{abs(hash(str(repo_path.resolve()))) % 10000}"

    return {
        "id": repo_id,
        "name": clean_name,
        "path": str(repo_path.resolve()),
        "status": status,
        "days_since_last_commit": days_since_last,
        "first_commit_date": first_dt.strftime("%Y-%m-%d"),
        "last_commit_date": last_dt.strftime("%Y-%m-%d"),
        "birth_year": first_dt.year,
        "death_year": last_dt.year,
        "total_commits": total_commits,
        "author_count": author_count,
        "number_of_authors": author_count,
        "last_commit_message": last_message,
        "last_author": last_author,
        "top_files": top_files,
        "readme_preview": readme_line,
        "first_line_of_readme": readme_line,
        "todo_count": todo_count,
        "count_of_todos": todo_count,
        "cause_of_death": cause_of_death,
        "revival_score": revival_score,
        "last_5_commits": [c.strip() for c in run_git(["log", "-5", "--format=%s"], repo_path, timeout=5).splitlines() if c.strip()] or [last_message],
        "todo_lines": get_todo_lines(repo_path, max_lines=5),
        "epitaph": None, # Filled later or cached
    }

def scan_directory_for_repos(
    root_path: Path,
    max_depth: int = SCAN_MAX_DEPTH,
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
) -> List[Dict[str, Any]]:
    """Scan root_path recursively up to max_depth, discovering and analyzing git repos."""
    discovered_paths: List[Path] = []

    def _walk(current: Path, depth: int):
        if depth > max_depth:
            return
        try:
            # Check if this directory itself is a git repo
            if (current / ".git").is_dir():
                discovered_paths.append(current)
                # Don't recurse into subdirectories of a git repo
                return

            subdirs = []
            for entry in os.scandir(str(current)):
                if entry.is_dir(follow_symlinks=False):
                    name = entry.name
                    if name not in IGNORED_DIRS and not name.startswith("."):
                        subdirs.append(Path(entry.path))

            for sub in subdirs:
                _walk(sub, depth + 1)
        except (PermissionError, FileNotFoundError, OSError):
            return

    _walk(root_path, 0)

    total_found = len(discovered_paths)
    results = []

    for idx, rpath in enumerate(discovered_paths):
        if progress_callback:
            progress_callback(rpath.name, idx + 1, total_found)
        try:
            facts = extract_repo_facts(rpath)
            if facts:
                results.append(facts)
        except Exception as e:
            continue

    # Sort repos: dead and ancient first (by days since last commit descending), then sleeping, then alive
    status_order = {"ancient": 0, "dead": 1, "sleeping": 2, "alive": 3}
    results.sort(key=lambda r: (status_order.get(r["status"], 4), -r["days_since_last_commit"]))

    return results
