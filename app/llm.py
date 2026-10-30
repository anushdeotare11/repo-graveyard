"""Ollama client and prompt engine for local Gemma inference."""
import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Dict, Any, AsyncGenerator, Optional
import httpx

from app.config import (
    OLLAMA_MODEL,
    OLLAMA_BASE_URL,
    OLLAMA_KEEP_ALIVE,
    NUM_PREDICT_EPITAPH,
    NUM_PREDICT_STORY,
    NUM_PREDICT_RESURRECT,
    TEMPERATURE,
    EPITAPHS_CACHE_FILE,
    STORIES_CACHE_FILE,
    RESURRECT_CACHE_FILE,
)

logger = logging.getLogger(__name__)

# In-memory and disk caching
def load_cache(cache_file: Path) -> Dict[str, Any]:
    if cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_cache(cache_file: Path, data: Dict[str, Any]):
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"Failed to save cache to {cache_file}: {e}")

epitaphs_cache = load_cache(EPITAPHS_CACHE_FILE)
stories_cache = load_cache(STORIES_CACHE_FILE)
resurrect_cache = load_cache(RESURRECT_CACHE_FILE)

async def check_ollama_status() -> Dict[str, Any]:
    """Verify Ollama server is running and the configured model is installed."""
    try:
        async with httpx.AsyncClient(base_url=OLLAMA_BASE_URL, timeout=3.0) as client:
            resp = await client.get("/api/tags")
            if resp.status_code == 200:
                data = resp.json()
                models = [m.get("name", "") for m in data.get("models", [])]
                # Match full name (e.g. "gemma3:4b") or prefix
                target_base = OLLAMA_MODEL.split(":")[0]
                has_model = any(OLLAMA_MODEL in m or (target_base in m and "4b" in m) for m in models)
                return {
                    "connected": True,
                    "target_model": OLLAMA_MODEL,
                    "model_available": has_model,
                    "installed_models": models,
                    "error": None if has_model else f"Model '{OLLAMA_MODEL}' not found. Run: ollama pull {OLLAMA_MODEL}"
                }
            return {
                "connected": False,
                "target_model": OLLAMA_MODEL,
                "model_available": False,
                "error": f"Ollama returned HTTP status {resp.status_code}"
            }
    except Exception as exc:
        return {
            "connected": False,
            "target_model": OLLAMA_MODEL,
            "model_available": False,
            "error": f"Ollama not running at {OLLAMA_BASE_URL}. Ensure Ollama is active. ({str(exc)})"
        }

SYSTEM_PROMPT_RULES = """You are the grave-keeper of "Repo Graveyard", an atmospheric resting place for abandoned code.
MANDATORY RULES:
1. Use ONLY the supplied facts (name, dates, commit count, cause of death, last commit message, TODO count, README first line).
2. Never invent features, people, technologies, or events not present in the facts.
3. Tone: Dark-funny and affectionate, short sentences, no cliches (no "In the dead of night", "digital shadows", etc.).
4. Never output source code or code blocks.
5. Output ONLY the requested text without introductory remarks or conversational filler."""

KNOWN_TECH_KEYWORDS = {
    "python", "javascript", "typescript", "rust", "golang", "react", "vue",
    "angular", "svelte", "docker", "kubernetes", "k8s", "aws", "azure", "gcp",
    "graphql", "mongodb", "postgresql", "postgres", "redis", "sqlite",
    "solidity", "ethereum", "webgpu", "pytorch", "tensorflow", "fastapi",
    "django", "flask", "ruby", "rails", "php", "laravel", "swift", "kotlin",
    "nextjs", "nuxt", "tailwind", "electron", "wasm"
}

def _has_ungrounded_tech(output_text: str, repo: Dict[str, Any]) -> Optional[str]:
    """Return tech name if output names a technology not present in the input facts."""
    input_corpus = (
        f"{repo.get('name', '')} "
        f"{repo.get('last_commit_message', '')} "
        f"{repo.get('first_line_of_readme', '')} "
        f"{repo.get('readme_preview', '')} "
        f"{' '.join(repo.get('top_files', []))} "
        f"{' '.join(repo.get('last_5_commits', []))} "
        f"{' '.join(repo.get('todo_lines', []))}"
    ).lower()

    output_low = output_text.lower()
    for tech in KNOWN_TECH_KEYWORDS:
        if re.search(rf"\b{re.escape(tech)}\b", output_low):
            if not re.search(rf"\b{re.escape(tech)}\b", input_corpus):
                return tech
    return None

def _clean_response(text: str) -> str:
    """Strip quotes, Markdown code blocks, and introductory filler."""
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = text.strip().strip('"').strip("'").strip()
    # Strip common preambles like "Epitaph:" or "Ghost story:"
    text = re.sub(r"^(epitaph|ghost story|inscription):\s*", "", text, flags=re.IGNORECASE)
    return text.strip()

def _validate_epitaph(text: str) -> bool:
    """Validate epitaph is 1-2 lines and around 8-35 words."""
    cleaned = _clean_response(text)
    words = cleaned.split()
    lines = [ln for ln in cleaned.splitlines() if ln.strip()]
    if len(lines) > 2:
        return False
    if not (6 <= len(words) <= 38):
        return False
    if "```" in text:
        return False
    return True

async def _call_ollama(prompt: str, num_predict: int, temperature: float = TEMPERATURE) -> str:
    """Execute raw non-streaming prompt call to Ollama."""
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": {
            "num_predict": num_predict,
            "temperature": temperature,
        }
    }
    async with httpx.AsyncClient(base_url=OLLAMA_BASE_URL, timeout=35.0) as client:
        resp = await client.post("/api/generate", json=payload)
        if resp.status_code == 200:
            return resp.json().get("response", "").strip()
    return ""

async def generate_epitaph(repo: Dict[str, Any], force_refresh: bool = False) -> str:
    """Generate a 1-2 line tombstone epitaph using only supplied facts with 1 server-side retry."""
    repo_id = repo.get("id") or repo.get("name")
    if not force_refresh and repo_id in epitaphs_cache and epitaphs_cache[repo_id]:
        return epitaphs_cache[repo_id]

    # Deterministic factual fallback if Ollama is unreachable
    name = repo.get("name", "Project")
    commits = repo.get("total_commits", 0)
    cause = repo.get("cause_of_death", "Fizzled out")
    fallback_epitaph = f"Here rests {name}. Abandoned after {commits} commits. Cause of death: {cause}."

    prompt = f"""{SYSTEM_PROMPT_RULES}

Task: Write a 1-2 line tombstone epitaph for this abandoned repository.
FACTS:
- Name: {name}
- Dates: {repo.get('birth_year', repo.get('first_commit_date', ''))} — {repo.get('death_year', repo.get('last_commit_date', ''))}
- Commits: {commits}
- Cause of Death: {cause}
- Last Commit: "{repo.get('last_commit_message', 'none')}"
- TODO count: {repo.get('todo_count', repo.get('count_of_todos', 0))}
- README first line: "{repo.get('first_line_of_readme', repo.get('readme_preview', 'none'))}"

INSTRUCTION: Exactly 1 or 2 short sentences. Under 25 words total. Grounded strictly in the facts."""

    try:
        raw = await _call_ollama(prompt, num_predict=NUM_PREDICT_EPITAPH, temperature=0.7)
        cleaned = _clean_response(raw)

        # Validate length server-side and retry once if off
        if not _validate_epitaph(cleaned):
            retry_prompt = f"""{SYSTEM_PROMPT_RULES}
Rewrite this epitaph into strictly 1 or 2 short sentences under 25 words:
"{cleaned}"
Output ONLY the 1-2 line inscription."""
            raw_retry = await _call_ollama(retry_prompt, num_predict=NUM_PREDICT_EPITAPH, temperature=0.5)
            retry_cleaned = _clean_response(raw_retry)
            if _validate_epitaph(retry_cleaned):
                cleaned = retry_cleaned
            else:
                sentences = [s.strip() for s in cleaned.split(".") if s.strip()]
                cleaned = ". ".join(sentences[:2]) + "."

        # Grounding check: if ungrounded technology is detected, regenerate once
        ungrounded = _has_ungrounded_tech(cleaned, repo)
        if ungrounded:
            logger.info(f"Epitaph contains ungrounded tech '{ungrounded}'. Regenerating once...")
            tech_retry_prompt = f"""{SYSTEM_PROMPT_RULES}
WARNING: Your previous draft mentioned '{ungrounded}', which does NOT appear in the facts. Do not invent any technologies.
Rewrite the 1-2 line epitaph based strictly on these facts:
- Name: {name}
- Dates: {repo.get('birth_year', repo.get('first_commit_date', ''))} — {repo.get('death_year', repo.get('last_commit_date', ''))}
- Commits: {commits}
- Cause of Death: {cause}
- Last Commit: "{repo.get('last_commit_message', 'none')}"
- TODO count: {repo.get('todo_count', repo.get('count_of_todos', 0))}
- README first line: "{repo.get('first_line_of_readme', repo.get('readme_preview', 'none'))}"
INSTRUCTION: Under 25 words total. Grounded strictly in the facts."""
            raw_tech_retry = await _call_ollama(tech_retry_prompt, num_predict=NUM_PREDICT_EPITAPH, temperature=0.3)
            tech_cleaned = _clean_response(raw_tech_retry)
            if not _has_ungrounded_tech(tech_cleaned, repo) and len(tech_cleaned.split()) >= 4:
                cleaned = tech_cleaned
            else:
                cleaned = fallback_epitaph

        if len(cleaned.split()) >= 4:
            epitaphs_cache[repo_id] = cleaned
            save_cache(EPITAPHS_CACHE_FILE, epitaphs_cache)
            return cleaned
    except Exception as e:
        logger.warning(f"Ollama epitaph error for {name}: {e}")

    epitaphs_cache[repo_id] = fallback_epitaph
    save_cache(EPITAPHS_CACHE_FILE, epitaphs_cache)
    return fallback_epitaph

def _validate_story(text: str) -> bool:
    """Validate ghost story is roughly 80 words (55-105 words) in first person with no code."""
    cleaned = _clean_response(text)
    words = cleaned.split()
    if not (50 <= len(words) <= 110):
        return False
    if "```" in text:
        return False
    # Check first-person voice
    low = cleaned.lower()
    if not ("i " in low or "my " in low or "i'm" in low or "i've" in low or "i was" in low):
        return False
    return True

async def generate_ghost_story_text(repo: Dict[str, Any], force_refresh: bool = False) -> str:
    """Generate and validate a ~80-word ghost story in the repo's own voice with 1 retry."""
    repo_id = repo.get("id") or repo.get("name")
    if not force_refresh and repo_id in stories_cache and stories_cache[repo_id]:
        return stories_cache[repo_id]

    name = repo.get("name", "Project")
    commits = repo.get("total_commits", 0)
    cause = repo.get("cause_of_death", "Fizzled out")
    last_msg = repo.get("last_commit_message", "wip")
    todos = repo.get("todo_count", repo.get("count_of_todos", 0))
    readme = repo.get("first_line_of_readme", repo.get("readme_preview", "A software project."))
    first_date = repo.get("first_commit_date", repo.get("birth_year", "2022"))
    last_date = repo.get("last_commit_date", repo.get("death_year", "2023"))

    fallback_story = (
        f"I am {name}. I was born on {first_date} to build {readme}. "
        f"For {commits} commits my terminal glowed with hope. But then came my final commit: '{last_msg}'. "
        f"With {todos} unresolved TODOs still lingering in my files, silence fell. My cause of death was {cause}. "
        f"Now my ghost drifts through empty git branches, wondering what might have been."
    )

    prompt = f"""{SYSTEM_PROMPT_RULES}

Task: Write a ~80-word ghost story in the FIRST PERSON ("I was built to..."). You are the spirit of this dead repository.
FACTS:
- Name: {name}
- Lifespan: {first_date} to {last_date} ({repo.get('days_since_last_commit', 0)} days of silence)
- Total Commits: {commits}
- Cause of Death: {cause}
- Last Commit: "{last_msg}"
- Unfinished TODO count: {todos}
- README first line: "{readme}"

RULES:
- Word count: approximately 75 to 85 words.
- In the repo's own voice (first-person).
- Use ONLY the supplied facts above. Never invent extra features or people.
- Dark-funny and affectionate. Short sentences. No cliches.
- Output ONLY the story."""

    try:
        raw = await _call_ollama(prompt, num_predict=NUM_PREDICT_STORY, temperature=0.7)
        cleaned = _clean_response(raw)

        # Server-side validation: ~80 words
        if not _validate_story(cleaned):
            words = cleaned.split()
            retry_prompt = f"""{SYSTEM_PROMPT_RULES}
Rewrite this ghost story to be approximately 80 words in the first person ('I...').
Previous length was {len(words)} words.
Original text: "{cleaned}"
Facts: name={name}, commits={commits}, last_commit="{last_msg}", todos={todos}, cause={cause}.
Output ONLY the story text."""
            raw_retry = await _call_ollama(retry_prompt, num_predict=NUM_PREDICT_STORY, temperature=0.5)
            retry_cleaned = _clean_response(raw_retry)
            if len(retry_cleaned.split()) >= 45:
                cleaned = retry_cleaned

        # Grounding check: if ungrounded technology is detected, regenerate once
        ungrounded = _has_ungrounded_tech(cleaned, repo)
        if ungrounded:
            logger.info(f"Ghost story contains ungrounded tech '{ungrounded}'. Regenerating once...")
            tech_retry_prompt = f"""{SYSTEM_PROMPT_RULES}
WARNING: Your previous draft mentioned '{ungrounded}', which does NOT exist in the facts. Do NOT invent technologies or people.
Rewrite the ~80-word ghost story in first person ('I was built to...') based strictly on these facts:
- Name: {name}
- Lifespan: {first_date} to {last_date}
- Total Commits: {commits}
- Cause of Death: {cause}
- Last Commit: "{last_msg}"
- Unfinished TODO count: {todos}
- README first line: "{readme}"
Output ONLY the story text."""
            raw_tech = await _call_ollama(tech_retry_prompt, num_predict=NUM_PREDICT_STORY, temperature=0.3)
            tech_cleaned = _clean_response(raw_tech)
            if not _has_ungrounded_tech(tech_cleaned, repo) and len(tech_cleaned.split()) >= 40:
                cleaned = tech_cleaned
            else:
                cleaned = fallback_story

        if len(cleaned.split()) >= 30:
            stories_cache[repo_id] = cleaned
            save_cache(STORIES_CACHE_FILE, stories_cache)
            return cleaned
    except Exception as e:
        logger.warning(f"Ollama ghost story error for {name}: {e}")

    stories_cache[repo_id] = fallback_story
    save_cache(STORIES_CACHE_FILE, stories_cache)
    return fallback_story

async def stream_ghost_story(repo: Dict[str, Any], force_refresh: bool = False) -> AsyncGenerator[str, None]:
    """Stream ghost story token-by-token using direct Ollama SSE streaming for low TTFT (< 2s)."""
    repo_id = repo.get("id") or repo.get("name")
    
    # Check Ollama status
    status = await check_ollama_status()
    ollama_ok = status.get("connected") and status.get("model_available")

    # If already cached and not refreshing, stream cached version instantly (< 20ms TTFT)
    if not force_refresh and repo_id in stories_cache and stories_cache[repo_id]:
        cached_story = stories_cache[repo_id]
        words = cached_story.split(" ")
        for i, word in enumerate(words):
            token = word + (" " if i < len(words) - 1 else "")
            yield json.dumps({"token": token, "done": False, "cached": True})
            await asyncio.sleep(0.01)
        yield json.dumps({"token": "", "done": True, "full": cached_story, "cached": True})
        return

    name = repo.get("name", "Project")
    commits = repo.get("total_commits", 0)
    cause = repo.get("cause_of_death", "Fizzled out")
    last_msg = repo.get("last_commit_message", "wip")
    todos = repo.get("todo_count", repo.get("count_of_todos", 0))
    readme = repo.get("first_line_of_readme", repo.get("readme_preview", "A software project."))
    first_date = repo.get("first_commit_date", repo.get("birth_year", "2022"))
    last_date = repo.get("last_commit_date", repo.get("death_year", "2023"))

    fallback_story = (
        f"I am {name}. I was born on {first_date} to build {readme}. "
        f"For {commits} commits my terminal glowed with life, ending with '{last_msg}'. "
        f"With {todos} unresolved TODOs still lingering, silence fell. Cause of death: {cause}. "
        f"Now my ghost drifts through empty git branches, wondering what might have been."
    )

    if not ollama_ok:
        err_msg = status.get("error") or "Ollama is not running."
        yield json.dumps({
            "token": fallback_story,
            "done": True,
            "full": fallback_story,
            "ollama_error": err_msg,
            "fallback": True
        })
        return

    prompt = f"""{SYSTEM_PROMPT_RULES}

Task: Write a ~80-word ghost story in the FIRST PERSON ("I was built to..."). You are the spirit of this dead repository.
FACTS:
- Name: {name}
- Lifespan: {first_date} to {last_date} ({repo.get('days_since_last_commit', 0)} days of silence)
- Total Commits: {commits}
- Cause of Death: {cause}
- Last Commit: "{last_msg}"
- Unfinished TODO count: {todos}
- README first line: "{readme}"

RULES:
- Word count: approximately 75 to 85 words.
- In the repo's own voice (first-person).
- Use ONLY the supplied facts above. Never invent extra features or people.
- Dark-funny and affectionate. Short sentences. No cliches.
- Output ONLY the story."""

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": True,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": {
            "num_predict": NUM_PREDICT_STORY,
            "temperature": 0.65,
        }
    }

    accumulated = []
    try:
        async with httpx.AsyncClient(base_url=OLLAMA_BASE_URL, timeout=35.0) as client:
            async with client.stream("POST", "/api/generate", json=payload) as resp:
                if resp.status_code == 200:
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        chunk = json.loads(line)
                        token = chunk.get("response", "")
                        if token:
                            accumulated.append(token)
                            yield json.dumps({"token": token, "done": False})
                        if chunk.get("done", False):
                            break

        full_raw = "".join(accumulated)
        cleaned = _clean_response(full_raw)

        # Grounding check on finished stream: if ungrounded tech detected, regenerate once
        ungrounded = _has_ungrounded_tech(cleaned, repo)
        if ungrounded:
            logger.info(f"Streamed story contained ungrounded tech '{ungrounded}'. Regenerating clean version...")
            cleaned = await generate_ghost_story_text(repo, force_refresh=True)

        if len(cleaned.split()) >= 30:
            stories_cache[repo_id] = cleaned
            save_cache(STORIES_CACHE_FILE, stories_cache)

        yield json.dumps({"token": "", "done": True, "full": cleaned or fallback_story})
        return
    except Exception as exc:
        logger.warning(f"Direct stream error: {exc}")

    # Fallback if streaming failed
    yield json.dumps({"token": fallback_story, "done": True, "full": fallback_story, "fallback": True})

async def stream_resurrect_plan(repo: Dict[str, Any]) -> AsyncGenerator[str, None]:
    """Stream a concrete 3-step resurrection plan using ONLY allowed facts: README first lines, TODO lines, and last 5 commit messages."""
    repo_id = repo.get("id") or repo.get("name")
    name = repo.get("name", "Project")

    status = await check_ollama_status()
    if not status.get("connected") or not status.get("model_available"):
        fallback = (
            f"1. Resume where you left off: address the last commit message '{repo.get('last_commit_message', 'wip')}'.\n"
            f"2. Exorcise the {repo.get('todo_count', 0)} unresolved TODOs in tracked files.\n"
            f"3. Re-run tests, update dependencies, and commit a clean revival release."
        )
        yield json.dumps({"token": fallback, "done": True, "full": fallback, "fallback": True})
        return

    readme_content = repo.get("first_line_of_readme") or repo.get("readme_preview") or "No README description."
    todo_lines = repo.get("todo_lines", [])
    if not todo_lines:
        todo_count = repo.get("todo_count", repo.get("count_of_todos", 0))
        todo_lines = [f"TODO: resolve outstanding items ({todo_count} comments in code)"] if todo_count > 0 else ["No open TODO comments found."]
    todo_text = "\n".join(f"- {t}" for t in todo_lines[:5])

    last_5 = repo.get("last_5_commits", [])
    if not last_5 and repo.get("last_commit_message"):
        last_5 = [repo.get("last_commit_message")]
    commits_text = "\n".join(f"- {c}" for c in last_5[:5]) if last_5 else "- Initial commit"

    prompt = f"""You are resurrecting an abandoned software repository. Provide a concrete 3-step revival plan based ONLY on these supplied inputs:

README FIRST LINES:
{readme_content}

TODO LINES:
{todo_text}

LAST 5 COMMIT MESSAGES:
{commits_text}

RULES:
- Provide exactly 3 numbered steps.
- Each step must be 1 to 2 short sentences proposing a concrete action based ONLY on the README, TODO lines, and last 5 commit messages above.
- Do not invent external technologies or people.
- Do not output source code.
- Output ONLY the 3 numbered steps."""

    try:
        plan_text = await _call_ollama(prompt, num_predict=NUM_PREDICT_RESURRECT, temperature=0.6)
        plan_cleaned = _clean_response(plan_text)

        # Grounding check: if ungrounded technology is detected, regenerate once
        ungrounded = _has_ungrounded_tech(plan_cleaned, repo)
        if ungrounded:
            logger.info(f"Resurrection plan contains ungrounded tech '{ungrounded}'. Regenerating once...")
            retry_prompt = f"""You are resurrecting an abandoned software repository.
WARNING: Do NOT mention '{ungrounded}' or any technologies not in the facts below.
Provide a concrete 3-step revival plan based ONLY on these supplied inputs:

README FIRST LINES:
{readme_content}

TODO LINES:
{todo_text}

LAST 5 COMMIT MESSAGES:
{commits_text}

RULES:
- Provide exactly 3 numbered steps.
- Each step must be 1 to 2 short sentences proposing a concrete action based ONLY on the inputs above.
- Output ONLY the 3 numbered steps."""
            raw_retry = await _call_ollama(retry_prompt, num_predict=NUM_PREDICT_RESURRECT, temperature=0.3)
            retry_cleaned = _clean_response(raw_retry)
            if not _has_ungrounded_tech(retry_cleaned, repo) and len(retry_cleaned.split()) >= 15:
                plan_cleaned = retry_cleaned

        if len(plan_cleaned.split()) >= 15:
            resurrect_cache[repo_id] = plan_cleaned
            save_cache(RESURRECT_CACHE_FILE, resurrect_cache)
            tokens = re.findall(r"\S+|\s+", plan_cleaned)
            for token in tokens:
                yield json.dumps({"token": token, "done": False})
                await asyncio.sleep(0.01)
            yield json.dumps({"token": "", "done": True, "full": plan_cleaned})
            return
    except Exception as e:
        logger.warning(f"Resurrection plan error: {e}")

    fallback = (
        f"1. Reopen the repository and resolve the last commit: '{repo.get('last_commit_message', 'wip')}'.\n"
        f"2. Eliminate the {repo.get('todo_count', 0)} unresolved TODO comments.\n"
        f"3. Run the test suite and publish a fresh release."
    )
    yield json.dumps({"token": fallback, "done": True, "full": fallback, "fallback": True})
