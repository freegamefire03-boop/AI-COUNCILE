/* Planning Council v0 — Frontend */

const CONFIG = {
  owner: "freegamefire03-boop",
  repo: "ai-councile",
  dataBranch: "planner-data",
  pollIntervalMs: 6000,
};

const STEP_LABELS = {
  FILES_PARSED:                  "Input parsed",
  CEO_INTAKE_COMPLETE:           "CEO intake",
  BRIEF_COMPLETE:                "Planning brief",
  MEMBER_1_PRODUCT_COMPLETE:     "Product analyst",
  MEMBER_2_CONSTRAINTS_COMPLETE: "Constraint analyst",
  MEMBER_3_ARCHITECT_COMPLETE:   "Solution architect",
  MEMBER_4_EXECUTION_COMPLETE:   "Execution planner",
  MEMBER_5_REDTEAM_COMPLETE:     "Red team review",
  SYNTHESIS_COMPLETE:            "CEO synthesis",
  PLAN_FINALIZED:                "Plan finalized",
};
const ALL_STEPS = Object.keys(STEP_LABELS);

let currentProjectId = null;
let pollTimer = null;
let openrouterKey = null;
let ghToken = null;

// ── GitHub API ────────────────────────────────────────────────────────────

function ghHeaders() {
  return {
    Authorization: `token ${ghToken}`,
    "Content-Type": "application/json",
    Accept: "application/vnd.github.v3+json",
  };
}

async function ghReadFile(path, branch = CONFIG.dataBranch) {
  const url = `https://api.github.com/repos/${CONFIG.owner}/${CONFIG.repo}/contents/${path}?ref=${branch}&t=${Date.now()}`;
  const resp = await fetch(url, { headers: ghHeaders() });
  if (!resp.ok) return null;
  const data = await resp.json();
  const content = decodeURIComponent(escape(atob(data.content.replace(/\n/g, ""))));
  return { content, sha: data.sha };
}

async function ghWriteFile(path, content, branch = CONFIG.dataBranch) {
  const encoded = btoa(unescape(encodeURIComponent(content)));
  const existing = await ghReadFile(path, branch);
  const body = { message: `planner: ${path}`, content: encoded, branch };
  if (existing?.sha) body.sha = existing.sha;
  const url = `https://api.github.com/repos/${CONFIG.owner}/${CONFIG.repo}/contents/${path}`;
  const resp = await fetch(url, { method: "PUT", headers: ghHeaders(), body: JSON.stringify(body) });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(`Write failed: ${resp.status} — ${err.message || ""}`);
  }
  return resp.json();
}

async function triggerWorkflow(projectId, action) {
  const url = `https://api.github.com/repos/${CONFIG.owner}/${CONFIG.repo}/dispatches`;
  const resp = await fetch(url, {
    method: "POST", headers: ghHeaders(),
    body: JSON.stringify({
      event_type: "planner_run",
      client_payload: { project_id: projectId, action, openrouter_key: openrouterKey },
    }),
  });
  if (!resp.ok && resp.status !== 204) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(`Trigger failed: ${resp.status} — ${err.message || ""}`);
  }
}

async function ensureDataBranch() {
  const r = await fetch(
    `https://api.github.com/repos/${CONFIG.owner}/${CONFIG.repo}/branches/${CONFIG.dataBranch}`,
    { headers: ghHeaders() }
  );
  if (r.ok) return;
  const mainR = await fetch(
    `https://api.github.com/repos/${CONFIG.owner}/${CONFIG.repo}/git/refs/heads/main`,
    { headers: ghHeaders() }
  );
  const { object: { sha } } = await mainR.json();
  await fetch(`https://api.github.com/repos/${CONFIG.owner}/${CONFIG.repo}/git/refs`, {
    method: "POST", headers: ghHeaders(),
    body: JSON.stringify({ ref: `refs/heads/${CONFIG.dataBranch}`, sha }),
  });
}

// ── History (stored in planner-data/projects/history.json) ───────────────

async function loadHistory() {
  try {
    const file = await ghReadFile("projects/history.json");
    if (!file) return [];
    return JSON.parse(file.content);
  } catch { return []; }
}

async function appendHistory(entry) {
  let history = await loadHistory();
  // Remove duplicate if re-run
  history = history.filter(e => e.project_id !== entry.project_id);
  history.unshift(entry);          // newest first
  if (history.length > 50) history = history.slice(0, 50);
  await ghWriteFile("projects/history.json", JSON.stringify(history, null, 2));
}

async function updateHistoryStatus(projectId, status) {
  try {
    let history = await loadHistory();
    const idx = history.findIndex(e => e.project_id === projectId);
    if (idx !== -1) {
      history[idx].status = status;
      await ghWriteFile("projects/history.json", JSON.stringify(history, null, 2));
    }
  } catch { /* non-fatal */ }
}

function renderHistory(history) {
  const loading = document.getElementById("history-loading");
  const empty   = document.getElementById("history-empty");
  const list    = document.getElementById("history-list");

  loading.style.display = "none";
  list.innerHTML = "";

  if (!history.length) { empty.style.display = "block"; return; }
  empty.style.display = "none";

  for (const entry of history) {
    const item = document.createElement("div");
    item.className = "history-item" + (entry.project_id === currentProjectId ? " active-item" : "");
    item.onclick = () => openHistoryProject(entry);

    const promptEl = document.createElement("div");
    promptEl.className = "h-prompt";
    promptEl.textContent = entry.prompt || entry.project_id;

    const metaEl = document.createElement("div");
    metaEl.className = "h-meta";
    const badge = document.createElement("span");
    badge.className = "badge " + badgeClass(entry.status);
    badge.textContent = entry.status || "CREATED";
    const date = document.createElement("div");
    date.textContent = entry.created_at ? entry.created_at.slice(0, 10) : "";

    metaEl.appendChild(badge);
    metaEl.appendChild(date);
    item.appendChild(promptEl);
    item.appendChild(metaEl);
    list.appendChild(item);
  }
}

function badgeClass(status) {
  const map = {
    COMPLETE: "badge-done",
    EXECUTING_COUNCIL: "badge-running",
    BLOCKED_ON_HARD_DEPENDENCY: "badge-blocked",
  };
  return map[status] || "badge-created";
}

async function openHistoryProject(entry) {
  currentProjectId = entry.project_id;

  // Show status panel
  document.getElementById("status-section").style.display = "block";
  document.getElementById("result-section").style.display = "none";
  document.getElementById("error-box").style.display = "none";
  document.getElementById("project-id-display").textContent = `Project: ${entry.project_id}`;

  // Fetch current status
  const file = await ghReadFile(`projects/${entry.project_id}/status.json`);
  if (!file) {
    document.getElementById("status-text").textContent = "Status not found";
    return;
  }
  const status = JSON.parse(file.content);
  renderStatus(status);

  if (status.status === "COMPLETE") {
    document.getElementById("spinner").style.display = "none";
    await loadAndShowPlan(entry.project_id);
  } else if (status.status === "BLOCKED_ON_HARD_DEPENDENCY") {
    showError(status.error);
  } else if (status.status === "EXECUTING_COUNCIL" || status.status === "CREATED") {
    // Still running — resume polling
    document.getElementById("spinner").style.display = "block";
    startPolling();
  }
}

async function refreshHistory() {
  const history = await loadHistory();
  renderHistory(history);
}

// ── Project creation ──────────────────────────────────────────────────────

function generateProjectId() {
  const now = new Date();
  const pad = n => String(n).padStart(2, "0");
  const d = `${now.getFullYear()}${pad(now.getMonth()+1)}${pad(now.getDate())}`;
  const t = `${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
  return `proj_${d}_${t}_${Math.random().toString(36).slice(2,6)}`;
}

async function createProject(projectId, prompt) {
  const input = {
    project_id: projectId,
    created_at: new Date().toISOString(),
    prompt,
    options: { max_questions_per_batch: 0, interrupt_only_on_hard_dependency: true },
    files: [],
  };
  const initStatus = {
    project_id: projectId, status: "CREATED", ui_view: "PROGRESS_SPINNER",
    stage: "PROJECT_CREATED", updated_at: new Date().toISOString(),
    progress: { completed_steps: [], next_step: "FILES_PARSED" }, error: null, artifacts: [],
  };
  await ghWriteFile(`projects/${projectId}/input.json`, JSON.stringify(input, null, 2));
  await ghWriteFile(`projects/${projectId}/status.json`, JSON.stringify(initStatus, null, 2));

  // Save to history
  await appendHistory({
    project_id: projectId,
    prompt: prompt.slice(0, 120),
    created_at: new Date().toISOString(),
    status: "CREATED",
  });
}

// ── Polling ───────────────────────────────────────────────────────────────

async function pollStatus() {
  if (!currentProjectId) return;
  try {
    const file = await ghReadFile(`projects/${currentProjectId}/status.json`);
    if (!file) return;
    const status = JSON.parse(file.content);
    renderStatus(status);

    const evtFile = await ghReadFile(`projects/${currentProjectId}/events.json`);
    if (evtFile) renderEvents(JSON.parse(evtFile.content).events || []);

    if (status.status === "COMPLETE") {
      stopPolling();
      await updateHistoryStatus(currentProjectId, "COMPLETE");
      await loadAndShowPlan(currentProjectId);
      await refreshHistory();
    } else if (status.status === "BLOCKED_ON_HARD_DEPENDENCY") {
      stopPolling();
      await updateHistoryStatus(currentProjectId, "BLOCKED_ON_HARD_DEPENDENCY");
      showError(status.error);
      await refreshHistory();
    }
  } catch (e) { console.warn("Poll:", e); }
}

function startPolling() {
  stopPolling();
  pollTimer = setInterval(pollStatus, CONFIG.pollIntervalMs);
  pollStatus();
}
function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

// ── Render ────────────────────────────────────────────────────────────────

function renderStatus(status) {
  document.getElementById("stage-label").textContent =
    status.stage ? status.stage.replace(/_/g, " ") : "";
  document.getElementById("status-text").textContent = statusLabel(status.status);

  const completed = new Set(status.progress?.completed_steps || []);
  const nextStep  = status.progress?.next_step;
  const list = document.getElementById("steps-list");
  list.innerHTML = "";
  for (const step of ALL_STEPS) {
    const li = document.createElement("li");
    li.textContent = STEP_LABELS[step] || step;
    if (completed.has(step))    li.className = "done";
    else if (nextStep === step) li.className = "active";
    list.appendChild(li);
  }
  if (status.status === "COMPLETE") {
    document.getElementById("spinner").style.display = "none";
    document.getElementById("status-text").textContent = "Complete ✓";
  }
}

function statusLabel(s) {
  return { CREATED: "Starting...", EXECUTING_COUNCIL: "Council running...",
           COMPLETE: "Complete", BLOCKED_ON_HARD_DEPENDENCY: "Blocked" }[s] || s;
}

function renderEvents(events) {
  document.getElementById("events-log").innerHTML =
    events.slice(-30).reverse()
      .map(e => `<div>${e.at.slice(11,19)} ${e.message}</div>`).join("");
}

function showError(error) {
  const box = document.getElementById("error-box");
  document.getElementById("error-msg").textContent = error?.message || "An error occurred.";
  box.style.display = "flex";
  document.getElementById("spinner").style.display = "none";
}

async function loadAndShowPlan(projectId) {
  const file = await ghReadFile(`projects/${projectId}/artifacts/plan.md`);
  if (!file) return;
  document.getElementById("plan-output").textContent = file.content;
  document.getElementById("result-section").style.display = "block";
}

// ── Actions ───────────────────────────────────────────────────────────────

async function startRun() {
  const tok    = document.getElementById("gh-token").value.trim();
  const key    = document.getElementById("or-key").value.trim();
  const prompt = document.getElementById("prompt-input").value.trim();

  if (!tok)    { alert("Please enter your GitHub token."); return; }
  if (!key)    { alert("Please enter your OpenRouter API key."); return; }
  if (!prompt) { alert("Please enter a planning goal."); return; }

  ghToken = tok;
  openrouterKey = key;

  const btn = document.getElementById("run-btn");
  btn.disabled = true;
  btn.textContent = "Starting...";

  try {
    await ensureDataBranch();
    currentProjectId = generateProjectId();

    document.getElementById("project-id-display").textContent = `Project: ${currentProjectId}`;
    document.getElementById("status-section").style.display = "block";
    document.getElementById("result-section").style.display = "none";
    document.getElementById("error-box").style.display = "none";
    document.getElementById("spinner").style.display = "block";

    await createProject(currentProjectId, prompt);
    await new Promise(r => setTimeout(r, 1200));
    await triggerWorkflow(currentProjectId, "start");

    btn.textContent = "Running...";
    startPolling();
    await refreshHistory();
  } catch (e) {
    alert(`Error: ${e.message}`);
    btn.disabled = false;
    btn.textContent = "Run Planning Council";
  }
}

async function retryRun() {
  if (!currentProjectId) return;
  document.getElementById("error-box").style.display = "none";
  document.getElementById("spinner").style.display = "block";
  try {
    await triggerWorkflow(currentProjectId, "retry");
    startPolling();
  } catch (e) { alert(`Retry failed: ${e.message}`); }
}

// ── Init ──────────────────────────────────────────────────────────────────

window.addEventListener("DOMContentLoaded", async () => {
  // Load history on page open — requires token
  // We show a placeholder until user enters token
  // Actually: history is public on a public repo — read without token
  try {
    const url = `https://raw.githubusercontent.com/${CONFIG.owner}/${CONFIG.repo}/${CONFIG.dataBranch}/projects/history.json?t=${Date.now()}`;
    const r = await fetch(url);
    if (r.ok) {
      const history = await r.json();
      renderHistory(history);
    } else {
      document.getElementById("history-loading").style.display = "none";
      document.getElementById("history-empty").style.display = "block";
    }
  } catch {
    document.getElementById("history-loading").style.display = "none";
    document.getElementById("history-empty").style.display = "block";
  }
});
