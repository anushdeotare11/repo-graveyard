/**
 * Repo Graveyard Frontend Controller
 * Vanilla JS • SSE Streaming • 100% Offline Capable
 */

(function () {
  // Application State
  let repos = [];
  let currentActiveRepo = null;
  let storyEventSource = null;
  let seanceEventSource = null;
  let isScanning = false;

  // DOM Elements
  const scanForm = document.getElementById("scanForm");
  const scanPathInput = document.getElementById("scanPathInput");
  const scanBtn = document.getElementById("scanBtn");
  const scanProgressCard = document.getElementById("scanProgressCard");
  const scanStatusMsg = document.getElementById("scanStatusMsg");
  const scanCounters = document.getElementById("scanCounters");
  const scanProgressBar = document.getElementById("scanProgressBar");

  const livingStrip = document.getElementById("livingStrip");
  const livingSection = document.getElementById("livingSection");
  const cemeterySections = document.getElementById("cemeterySections");
  const emptyGraveyardMsg = document.getElementById("emptyGraveyardMsg");

  const totalDeadCount = document.getElementById("totalDeadCount");
  const totalLivingCount = document.getElementById("totalLivingCount");
  const totalTodosCount = document.getElementById("totalTodosCount");

  const filterSearchInput = document.getElementById("filterSearchInput");
  const sortSelect = document.getElementById("sortSelect");
  const demoModeBtn = document.getElementById("demoModeBtn");
  const openSeanceBtn = document.getElementById("openSeanceBtn");
  const openExportBtn = document.getElementById("openExportBtn");
  const batchEpitaphBtn = document.getElementById("batchEpitaphBtn");

  const ollamaStatusBadge = document.getElementById("ollamaStatusBadge");
  const ollamaStatusText = document.getElementById("ollamaStatusText");

  // Tombstone Modal Elements
  const tombstoneModal = document.getElementById("tombstoneModal");
  const modalCloseBtn = document.getElementById("modalCloseBtn");
  const modalRepoName = document.getElementById("modalRepoName");
  const modalLifespan = document.getElementById("modalLifespan");
  const modalCauseBadge = document.getElementById("modalCauseBadge");
  const modalRevivalScore = document.getElementById("modalRevivalScore");
  const modalTotalCommits = document.getElementById("modalTotalCommits");
  const modalDaysAgo = document.getElementById("modalDaysAgo");
  const modalLastAuthor = document.getElementById("modalLastAuthor");
  const modalTodoCount = document.getElementById("modalTodoCount");
  const modalLastMessage = document.getElementById("modalLastMessage");
  const modalTopFiles = document.getElementById("modalTopFiles");
  const ghostStoryText = document.getElementById("ghostStoryText");
  const storyStreamCursor = document.getElementById("storyStreamCursor");
  const storyFallbackBadge = document.getElementById("storyFallbackBadge");
  const regenStoryBtn = document.getElementById("regenStoryBtn");

  // Séance Modal Elements
  const seanceModal = document.getElementById("seanceModal");
  const seanceCloseBtn = document.getElementById("seanceCloseBtn");
  const seanceCandidateCard = document.getElementById("seanceCandidateCard");
  const seanceCandidateName = document.getElementById("seanceCandidateName");
  const seanceCandidateStats = document.getElementById("seanceCandidateStats");
  const seanceScoreNum = document.getElementById("seanceScoreNum");
  const seancePlanText = document.getElementById("seancePlanText");
  const seancePlanCursor = document.getElementById("seancePlanCursor");

  // Export Modal Elements
  const exportModal = document.getElementById("exportModal");
  const exportCloseBtn = document.getElementById("exportCloseBtn");
  const redactNamesCheckbox = document.getElementById("redactNamesCheckbox");
  const exportCountNum = document.getElementById("exportCountNum");
  const confirmExportBtn = document.getElementById("confirmExportBtn");

  // Tombstone shapes to cycle for visual interest
  const SHAPES = ["tomb-arch", "tomb-slab", "tomb-cross", "tomb-obelisk"];

  // Initialize
  async function init() {
    if (window.STANDALONE_EXPORT && window.EXPORT_REPOS) {
      // Standalone single-file export mode
      repos = window.EXPORT_REPOS;
      renderAll();
      setupExportMode();
      return;
    }

    // Check Ollama status
    await checkOllama();

    // Check URL parameters for ?demo=1 or ?demo=true
    const urlParams = new URLSearchParams(window.location.search);
    const isDemo = urlParams.get("demo") === "1" || urlParams.get("demo") === "true";

    // Load initial cached repos (or demo repos if ?demo=1)
    await loadRepos(isDemo);

    // Setup event listeners
    setupListeners();
  }

  function setupExportMode() {
    if (scanForm) scanForm.style.display = "none";
    if (demoModeBtn) demoModeBtn.style.display = "none";
    if (openExportBtn) openExportBtn.style.display = "none";
    if (batchEpitaphBtn) batchEpitaphBtn.style.display = "none";
    if (openSeanceBtn) openSeanceBtn.style.display = "none";
    if (ollamaStatusBadge) {
      ollamaStatusBadge.innerHTML = "<span>💾 Standalone Offline Archive</span>";
    }
    setupModalListenersOnly();
  }

  let epitaphPollInterval = null;

  async function checkOllama() {
    try {
      const res = await fetch("/api/status");
      const data = await res.json();
      const o = data.ollama;
      if (o && o.connected) {
        if (o.model_available) {
          ollamaStatusBadge.className = "badge badge-ai";
          ollamaStatusText.textContent = `Gemma 3:4b (Online)`;
          ollamaStatusBadge.style.color = "#34d399";
        } else {
          ollamaStatusBadge.className = "badge";
          ollamaStatusBadge.style.color = "#fcd34d";
          ollamaStatusText.textContent = `Model Missing (Run: ollama pull gemma3:4b)`;
        }
      } else {
        ollamaStatusBadge.className = "badge";
        ollamaStatusBadge.style.color = "#f87171";
        ollamaStatusText.textContent = "Ollama Offline (localhost:11434)";
      }
    } catch {
      if (ollamaStatusText) {
        ollamaStatusBadge.className = "badge";
        ollamaStatusBadge.style.color = "#f87171";
        ollamaStatusText.textContent = "Ollama Unreachable";
      }
    }
  }

  function startEpitaphPolling() {
    if (epitaphPollInterval) clearInterval(epitaphPollInterval);
    let polls = 0;
    epitaphPollInterval = setInterval(async () => {
      polls++;
      await loadRepos();
      const pending = repos.filter(
        (r) => (r.status === "dead" || r.status === "ancient") && (!r.epitaph || r.epitaph.includes("Inscribing"))
      );
      if (pending.length === 0 || polls >= 20) {
        clearInterval(epitaphPollInterval);
        epitaphPollInterval = null;
      }
    }, 3000);
  }

  async function loadRepos(demo = false) {
    try {
      const url = demo ? "/api/graveyard?demo=1" : "/api/graveyard";
      const res = await fetch(url);
      const data = await res.json();
      repos = Array.isArray(data) ? data : (data.repos || []);
      renderAll();
    } catch (err) {
      console.error("Failed to load repos:", err);
    }
  }

  function setupListeners() {
    // Scan Form
    if (scanForm) {
      scanForm.addEventListener("submit", (e) => {
        e.preventDefault();
        const path = scanPathInput.value.trim();
        if (path) startScanStream(path);
      });
    }

    // Demo Mode Button
    if (demoModeBtn) {
      demoModeBtn.addEventListener("click", async () => {
        demoModeBtn.disabled = true;
        demoModeBtn.innerHTML = "<span>Summoning Demo...</span>";
        try {
          await loadRepos(true);
        } catch (e) {
          console.error("Demo mode failed:", e);
        } finally {
          demoModeBtn.disabled = false;
          demoModeBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 3l14 9-14 9V3z"/></svg> Demo Mode`;
        }
      });
    }

    // Search and Sort
    if (filterSearchInput) {
      filterSearchInput.addEventListener("input", renderAll);
    }
    if (sortSelect) {
      sortSelect.addEventListener("change", renderAll);
    }

    // Batch Epitaphs
    if (batchEpitaphBtn) {
      batchEpitaphBtn.addEventListener("click", async () => {
        batchEpitaphBtn.disabled = true;
        batchEpitaphBtn.innerHTML = "<span>Inscribing in background...</span>";
        try {
          await fetch("/api/batch-epitaphs", { method: "POST" });
          setTimeout(loadRepos, 3000);
          setTimeout(loadRepos, 8000);
        } finally {
          setTimeout(() => {
            batchEpitaphBtn.disabled = false;
            batchEpitaphBtn.innerHTML = `<span>Inscribe Epitaphs</span>`;
          }, 3500);
        }
      });
    }

    // Séance Modal
    if (openSeanceBtn) {
      openSeanceBtn.addEventListener("click", startSeance);
    }
    if (seanceCloseBtn) {
      seanceCloseBtn.addEventListener("click", () => {
        if (seanceEventSource) seanceEventSource.close();
        seanceModal.classList.add("hidden");
      });
    }

    // Export Modal
    if (openExportBtn) {
      openExportBtn.addEventListener("click", () => {
        if (exportCountNum) exportCountNum.textContent = `${repos.length} repositories`;
        exportModal.classList.remove("hidden");
      });
    }
    if (exportCloseBtn) {
      exportCloseBtn.addEventListener("click", () => {
        exportModal.classList.add("hidden");
      });
    }
    if (confirmExportBtn) {
      confirmExportBtn.addEventListener("click", downloadExportHtml);
    }

    setupModalListenersOnly();
  }

  function setupModalListenersOnly() {
    // Tombstone Detail Modal Close
    if (modalCloseBtn) {
      modalCloseBtn.addEventListener("click", () => {
        if (storyEventSource) storyEventSource.close();
        tombstoneModal.classList.add("hidden");
      });
    }

    // Close on backdrop click
    window.addEventListener("click", (e) => {
      if (e.target === tombstoneModal) {
        if (storyEventSource) storyEventSource.close();
        tombstoneModal.classList.add("hidden");
      }
      if (e.target === seanceModal) {
        if (seanceEventSource) seanceEventSource.close();
        seanceModal.classList.add("hidden");
      }
      if (e.target === exportModal) {
        exportModal.classList.add("hidden");
      }
    });

    // Close on Escape key
    window.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        if (storyEventSource) storyEventSource.close();
        if (seanceEventSource) seanceEventSource.close();
        tombstoneModal.classList.add("hidden");
        seanceModal.classList.add("hidden");
        exportModal.classList.add("hidden");
      }
    });

    // Regenerate Story
    if (regenStoryBtn) {
      regenStoryBtn.addEventListener("click", () => {
        if (currentActiveRepo) {
          triggerStoryStream(currentActiveRepo, true);
        }
      });
    }
  }

  // Live SSE Scan Stream
  function startScanStream(path) {
    if (isScanning) return;
    isScanning = true;
    scanBtn.disabled = true;
    scanProgressCard.classList.remove("hidden");
    scanProgressBar.style.width = "10%";
    scanStatusMsg.textContent = `Awakening graveyard spirits in ${path}...`;
    scanCounters.textContent = "Scanning...";

    const sseUrl = `/api/scan/stream?path=${encodeURIComponent(path)}`;
    const eventSource = new EventSource(sseUrl);

    eventSource.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.error) {
          scanStatusMsg.textContent = `Error: ${data.error}`;
          eventSource.close();
          isScanning = false;
          scanBtn.disabled = false;
          return;
        }

        if (data.status === "analyzing") {
          scanStatusMsg.textContent = `Inspecting: ${data.repo_name}`;
          const current = data.current || 1;
          const total = data.total || 1;
          const pct = Math.min(95, Math.round((current / total) * 100));
          scanProgressBar.style.width = `${pct}%`;
          scanCounters.textContent = `${current} of ${total} repos analyzed`;
        } else if (data.status === "complete") {
          scanProgressBar.style.width = "100%";
          scanStatusMsg.textContent = `Exhumation complete. Found ${data.total_found} repositories!`;
          scanCounters.textContent = `${data.total_found} recorded`;
          repos = data.repos || [];
          renderAll();
          startEpitaphPolling();
          setTimeout(() => {
            scanProgressCard.classList.add("hidden");
            scanBtn.disabled = false;
            isScanning = false;
          }, 2000);
          eventSource.close();
        }
      } catch (err) {
        console.error("SSE parsing error:", err);
      }
    };

    eventSource.onerror = async (err) => {
      console.warn("SSE stream interrupted, falling back to POST /api/scan:", err);
      eventSource.close();
      try {
        scanStatusMsg.textContent = "Scanning directories via direct POST /api/scan...";
        const res = await fetch("/api/scan", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: path, max_depth: 3 })
        });
        if (res.ok) {
          const data = await res.json();
          repos = Array.isArray(data) ? data : (data.repos || []);
          scanProgressBar.style.width = "100%";
          scanStatusMsg.textContent = `Exhumation complete. Found ${repos.length} repositories!`;
          renderAll();
          startEpitaphPolling();
        } else {
          scanStatusMsg.textContent = "Scan encountered an error. Please verify the path.";
        }
      } catch (postErr) {
        scanStatusMsg.textContent = "Scan connection interrupted. Refreshing cached data...";
        loadRepos();
      } finally {
        setTimeout(() => {
          scanProgressCard.classList.add("hidden");
          scanBtn.disabled = false;
          isScanning = false;
        }, 1800);
      }
    };
  }

  // Render Everything
  function renderAll() {
    const query = (filterSearchInput ? filterSearchInput.value : "").toLowerCase().trim();
    const sortVal = sortSelect ? sortSelect.value : "age-desc";

    let filtered = repos.filter((r) => {
      if (!query) return true;
      return (
        r.name.toLowerCase().includes(query) ||
        r.cause_of_death.toLowerCase().includes(query) ||
        (r.last_commit_message && r.last_commit_message.toLowerCase().includes(query)) ||
        (r.epitaph && r.epitaph.toLowerCase().includes(query))
      );
    });

    // Sorting
    filtered.sort((a, b) => {
      if (sortVal === "age-desc") return b.days_since_last_commit - a.days_since_last_commit;
      if (sortVal === "age-asc") return a.days_since_last_commit - b.days_since_last_commit;
      if (sortVal === "commits-desc") return b.total_commits - a.total_commits;
      if (sortVal === "todos-desc") return b.todo_count - a.todo_count;
      if (sortVal === "revival-desc") return b.revival_score - a.revival_score;
      return 0;
    });

    const living = filtered.filter((r) => r.status === "alive" || r.status === "sleeping");
    const dead = filtered.filter((r) => r.status === "dead" || r.status === "ancient");

    // Update Counter Badges
    const allDead = repos.filter((r) => r.status === "dead" || r.status === "ancient");
    const allLiving = repos.filter((r) => r.status === "alive" || r.status === "sleeping");
    const allTodos = repos.reduce((acc, r) => acc + (r.todo_count || 0), 0);

    if (totalDeadCount) totalDeadCount.textContent = allDead.length;
    if (totalLivingCount) totalLivingCount.textContent = allLiving.length;
    if (totalTodosCount) totalTodosCount.textContent = allTodos;

    // Render Living Strip
    renderLivingStrip(living);

    // Render Cemetery Grounds
    renderCemeterySections(dead);

    // Empty state
    if (emptyGraveyardMsg) {
      if (filtered.length === 0) {
        emptyGraveyardMsg.classList.remove("hidden");
      } else {
        emptyGraveyardMsg.classList.add("hidden");
      }
    }
  }

  // Render "Still Among the Living"
  function renderLivingStrip(livingRepos) {
    if (!livingStrip || !livingSection) return;
    if (livingRepos.length === 0) {
      livingSection.style.display = "none";
      return;
    }

    livingSection.style.display = "block";
    livingStrip.innerHTML = livingRepos
      .map((r) => {
        const isAlive = r.status === "alive";
        return `
        <div class="living-pill-card" data-repo-id="${r.id || r.name}">
          <div class="living-meta-left">
            <span class="living-orb" style="background: ${isAlive ? '#34d399' : '#fbbf24'}; box-shadow: 0 0 10px ${isAlive ? '#34d399' : '#fbbf24'}"></span>
            <div>
              <div class="living-name">${escapeHtml(r.name)}</div>
              <div class="living-tag">${isAlive ? "Active Heartbeat" : "In Deep Slumber"}</div>
            </div>
          </div>
          <div class="living-days">${r.days_since_last_commit}d ago</div>
        </div>
      `;
      })
      .join("");

    // Add click to view facts even for living repos
    livingStrip.querySelectorAll(".living-pill-card").forEach((card) => {
      card.addEventListener("click", () => {
        const rid = card.getAttribute("data-repo-id");
        const found = repos.find((r) => (r.id || r.name) === rid);
        if (found) openTombstoneModal(found);
      });
    });
  }

  // Render Cemetery Sections Grouped by Passing Year
  function renderCemeterySections(deadRepos) {
    if (!cemeterySections) return;
    cemeterySections.innerHTML = "";

    if (deadRepos.length === 0) return;

    // Group repos by death year
    const yearGroups = {};
    deadRepos.forEach((r) => {
      const year = r.death_year || "Unknown";
      if (!yearGroups[year]) yearGroups[year] = [];
      yearGroups[year].push(r);
    });

    // Sort years descending
    const sortedYears = Object.keys(yearGroups).sort((a, b) => {
      const na = parseInt(a) || 0;
      const nb = parseInt(b) || 0;
      return nb - na;
    });

    sortedYears.forEach((year) => {
      const group = yearGroups[year];
      const sectionBlock = document.createElement("div");
      sectionBlock.className = "cemetery-section-block";

      const sectionTitle = getYearSectionTitle(year);

      sectionBlock.innerHTML = `
        <div class="cemetery-section-header">
          <h3 class="section-year-title">
            <span>🪦</span>
            ${sectionTitle}
          </h3>
          <span class="section-tomb-count">${group.length} plots</span>
        </div>
        <div class="tombstones-grid"></div>
      `;

      const grid = sectionBlock.querySelector(".tombstones-grid");

      group.forEach((repo, idx) => {
        const tombEl = createTombstoneElement(repo, idx);
        grid.appendChild(tombEl);
      });

      cemeterySections.appendChild(sectionBlock);
    });
  }

  function getYearSectionTitle(year) {
    const yNum = parseInt(year);
    if (!yNum) return `The Forgotten Catacombs (${year})`;
    const currentYear = new Date().getFullYear();
    if (yNum === currentYear) return `The Freshly Dug Grove (${year})`;
    if (yNum === currentYear - 1) return `The Silent Vaults (${year})`;
    if (yNum === currentYear - 2) return `The Mossy Crypts (${year})`;
    return `Ancient Catacombs of ${year}`;
  }

  function createTombstoneElement(repo, index) {
    const el = document.createElement("div");
    // Determine shape deterministically based on repo name hash
    const shapeClass = SHAPES[Math.abs(hashString(repo.name)) % SHAPES.length];
    el.className = `tombstone ${shapeClass}`;
    el.setAttribute("data-repo-id", repo.id || repo.name);

    const causeClass = getCauseClass(repo.cause_of_death);
    const isPending = !repo.epitaph;
    const epitaphText = repo.epitaph || "Resting in commit limbo. Awaiting digital eulogy...";

    el.innerHTML = `
      <div class="tomb-peak">
        <div class="tomb-rip">R . I . P</div>
        <div class="tomb-name" title="${escapeHtml(repo.name)}">${escapeHtml(repo.name)}</div>
        <div class="tomb-dates">${repo.birth_year} — ${repo.death_year}</div>
      </div>

      <div class="tomb-cause-wrap">
        <span class="cause-badge ${causeClass}">${escapeHtml(repo.cause_of_death)}</span>
      </div>

      <div class="tomb-inscription ${isPending ? 'placeholder-inscription' : ''}">
        ${escapeHtml(epitaphText)}
      </div>

      <div class="tomb-footer">
        <span class="tomb-metric" title="Total Commits">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="4"/><line x1="1.05" y1="12" x2="7" y2="12"/><line x1="17.01" y1="12" x2="22.96" y2="12"/></svg>
          ${repo.total_commits}
        </span>
        <span class="tomb-metric" title="Unfinished TODOs">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="9" y1="15" x2="15" y2="15"/></svg>
          ${repo.todo_count} TODOs
        </span>
        <span class="tomb-metric" title="Days since last commit">
          ${repo.days_since_last_commit}d ago
        </span>
      </div>

      <div class="tomb-moss-base"></div>
    `;

    el.addEventListener("click", () => openTombstoneModal(repo));
    return el;
  }

  function getCauseClass(cause) {
    if (!cause) return "";
    const c = cause.toLowerCase();
    if (c.includes("abandoned")) return "cause-abandoned";
    if (c.includes("young")) return "cause-young";
    if (c.includes("todo")) return "cause-todo";
    if (c.includes("burnout") || c.includes("paralysis")) return "cause-burnout";
    return "";
  }

  // Open Tombstone Inspection & Ghost Story Modal
  function openTombstoneModal(repo) {
    currentActiveRepo = repo;

    modalRepoName.textContent = repo.name;
    modalLifespan.textContent = `${repo.birth_year} — ${repo.death_year} (${repo.first_commit_date} to ${repo.last_commit_date})`;
    modalCauseBadge.textContent = repo.cause_of_death;
    modalCauseBadge.className = `cause-badge ${getCauseClass(repo.cause_of_death)}`;
    modalRevivalScore.textContent = `Revival Potential: ${repo.revival_score}/100`;

    modalTotalCommits.textContent = repo.total_commits;
    modalDaysAgo.textContent = `${repo.days_since_last_commit} days`;
    modalLastAuthor.textContent = repo.last_author || "Unknown";
    modalTodoCount.textContent = repo.todo_count;
    modalLastMessage.textContent = repo.last_commit_message ? `"${repo.last_commit_message}"` : "(No commit message)";

    // Top files
    if (repo.top_files && repo.top_files.length > 0) {
      modalTopFiles.innerHTML = repo.top_files.map((f) => `<span class="file-tag">${escapeHtml(f)}</span>`).join("");
    } else {
      modalTopFiles.innerHTML = `<span class="file-tag">No key files recorded</span>`;
    }

    tombstoneModal.classList.remove("hidden");

    // Reset fallback badge
    if (storyFallbackBadge) storyFallbackBadge.classList.add("hidden");

    // Stream or show ghost story
    triggerStoryStream(repo, false);
  }

  function triggerStoryStream(repo, forceRefresh) {
    if (storyEventSource) {
      storyEventSource.close();
      storyEventSource = null;
    }

    // In standalone export mode or if story already exists in memory and not forcing refresh
    if (window.STANDALONE_EXPORT || (!forceRefresh && repo.story)) {
      ghostStoryText.textContent = repo.story || "My spirit wanders these stone grounds in peaceful silence.";
      storyStreamCursor.classList.add("hidden");
      const ollamaDown = ollamaStatusText && (ollamaStatusText.textContent.includes("Offline") || ollamaStatusText.textContent.includes("Missing") || ollamaStatusText.textContent.includes("Unreachable"));
      if (storyFallbackBadge && (repo.fallback || (ollamaDown && !repo.is_ai_generated))) {
        storyFallbackBadge.classList.remove("hidden");
        storyFallbackBadge.textContent = "written without the model";
      }
      return;
    }

    ghostStoryText.textContent = "";
    storyStreamCursor.classList.remove("hidden");

    const rid = repo.id || repo.name;
    const url = `/api/story/${encodeURIComponent(rid)}?refresh=${forceRefresh ? "true" : "false"}`;

    storyEventSource = new EventSource(url);

    storyEventSource.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.fallback || data.ollama_error) {
          if (storyFallbackBadge) {
            storyFallbackBadge.classList.remove("hidden");
            storyFallbackBadge.textContent = "written without the model";
          }
        }
        if (data.ollama_error) {
          const banner = document.createElement("div");
          banner.className = "ollama-warning-box";
          banner.style.cssText = "padding: 8px 12px; margin-bottom: 12px; background: rgba(239, 68, 68, 0.15); border: 1px solid rgba(239, 68, 68, 0.35); border-radius: 6px; font-size: 0.82rem; color: #fca5a5;";
          banner.innerHTML = `⚠️ <strong>Local AI Notice:</strong> ${escapeHtml(data.ollama_error)}`;
          ghostStoryText.innerHTML = "";
          ghostStoryText.appendChild(banner);
        }
        if (data.token) {
          ghostStoryText.textContent += data.token;
        }
        if (data.done) {
          storyStreamCursor.classList.add("hidden");
          if (data.full) {
            repo.story = data.full;
            if (data.fallback) repo.fallback = true;
          }
          storyEventSource.close();
          storyEventSource = null;
        }
      } catch (err) {
        console.error("Story token parse error:", err);
      }
    };

    storyEventSource.onerror = (err) => {
      console.warn("Story EventSource error:", err);
      storyStreamCursor.classList.add("hidden");
      if (storyFallbackBadge) {
        storyFallbackBadge.classList.remove("hidden");
        storyFallbackBadge.textContent = "written without the model";
      }
      if (!ghostStoryText.textContent || ghostStoryText.textContent.includes("Summoning")) {
        ghostStoryText.innerHTML = `
          <div style="padding: 8px 12px; margin-bottom: 12px; background: rgba(239,68,68,0.15); border: 1px solid rgba(239,68,68,0.3); border-radius: 6px; font-size: 0.82rem; color: #fca5a5;">
            ⚠️ <em>Ollama is currently unreachable at localhost:11434. Displaying deterministic git history fallback.</em>
          </div>
          <div>I am ${escapeHtml(repo.name)}. For ${repo.total_commits} commits my terminal glowed with life, ending with '${escapeHtml(repo.last_commit_message || "none")}'. Cause of death: ${escapeHtml(repo.cause_of_death)}. Now my code rests in silence.</div>
        `;
      }
      storyEventSource.close();
      storyEventSource = null;
    };
  }

  // Séance (Resurrection)
  function startSeance() {
    seanceModal.classList.remove("hidden");
    seanceCandidateCard.classList.add("hidden");
    seancePlanText.textContent = "Summoning local necromancy circle...";
    seancePlanCursor.classList.remove("hidden");

    const statusPhrase = document.getElementById("seanceStatusPhrase");
    if (statusPhrase) {
      statusPhrase.textContent = "Lighting altar candles & calculating highest revival potential...";
    }

    if (seanceEventSource) {
      seanceEventSource.close();
      seanceEventSource = null;
    }

    let activeCandidate = null;
    const url = "/api/resurrect";
    seanceEventSource = new EventSource(url);

    seanceEventSource.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.type === "candidate") {
          activeCandidate = data.repo;
          seanceCandidateCard.classList.remove("hidden");
          seanceCandidateName.textContent = activeCandidate.name;
          seanceCandidateStats.textContent = `${activeCandidate.total_commits} commits • ${activeCandidate.days_since_last_commit} days silent • ${activeCandidate.todo_count} TODOs`;
          seanceScoreNum.textContent = activeCandidate.revival_score;
          seancePlanText.textContent = "";
          if (statusPhrase) {
            statusPhrase.textContent = `Vessel chosen: ${activeCandidate.name} (Revival Index: ${activeCandidate.revival_score}/100). Channeling plan...`;
          }
        } else if (data.token) {
          seancePlanText.textContent += data.token;
        }
        if (data.done) {
          seancePlanCursor.classList.add("hidden");
          if (statusPhrase && activeCandidate) {
            statusPhrase.textContent = `Séance complete. The 3-step resurrection path for ${activeCandidate.name} is revealed.`;
          }
          seanceEventSource.close();
          seanceEventSource = null;
        }
      } catch (err) {
        console.error("Séance parse error:", err);
      }
    };

    seanceEventSource.onerror = (err) => {
      console.warn("Séance error:", err);
      seancePlanCursor.classList.add("hidden");
      if (statusPhrase) {
        statusPhrase.textContent = "Séance complete (Offline fallback).";
      }
      if (!seancePlanText.textContent || seancePlanText.textContent.includes("Summoning")) {
        seancePlanText.textContent = "1. Revisit the final commit and resolve outstanding blockers.\n2. Exorcise open TODO comments in key files.\n3. Run a modern build pass and tag a revival release.";
      }
      seanceEventSource.close();
      seanceEventSource = null;
    };
  }

  // Export Graveyard Standalone HTML
  async function downloadExportHtml() {
    confirmExportBtn.disabled = true;
    confirmExportBtn.innerHTML = "<span>Compiling Archive...</span>";
    const redact = redactNamesCheckbox.checked;

    try {
      const res = await fetch("/api/export", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ redact }),
      });

      if (!res.ok) throw new Error("Export request failed");

      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = redact ? "repo_graveyard_redacted.html" : "repo_graveyard.html";
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
      exportModal.classList.add("hidden");
    } catch (err) {
      alert("Failed to export HTML: " + err.message);
    } finally {
      confirmExportBtn.disabled = false;
      confirmExportBtn.innerHTML = `
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
        Download Standalone HTML
      `;
    }
  }

  // Utilities
  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function hashString(str) {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
      hash = (hash << 5) - hash + str.charCodeAt(i);
      hash |= 0;
    }
    return hash;
  }

  // Boot on DOM ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
