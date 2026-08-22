/* Planning Council v0 — Frontend */

const CONFIG = {
  owner: "freegamefire03-boop",
  repo: "ai-councile",
  dataBranch: "planner-data",
  pollIntervalMs: 6000,
};

const STEP_LABELS = {
  FILES_PARSED: "Input parsed",
  CEO_INTAKE_COMPLETE: "CEO intake",
  BRIEF_COMPLETE: "Planning brief",
  MEMBER_1_PRODUCT_COMPLETE: "Product analyst",
  MEMBER_2_CONSTRAINTS_COMPLETE: "Constraint analyst",
  MEMBER_3_ARCHITECT_COMPLETE: "Solution architect",
  MEMBER_4_EXECUTION_COMPLETE: "Execution planner",
  MEMBER_5_REDTEAM_COMPLETE: "Red team review",
  SYNTHESIS_COMPLETE: "CEO synthesis",
  PLAN_FINALIZED: "Plan finalized",
};

const ALL_STEPS = Object.keys(STEP_LABELS);

let currentProjectId = null;
let pollTimer = null;
let openrouterKey = null;
let ghToken = null;

// ── GitHub API helpers ────────────────────────────────────────────────────

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

async function ghWriteFile(path, content, sha = null, branch = CONFIG.dataBranch) {
  const encoded = btoa(unescape(encodeURIComponent(content)));
  const body = {
    message: `planner: update ${path}`,
    content: encoded,
    branch,
  };
  if (sha) body.sha = sha;

  const url = `https://api.github.com/repos/${CONFIG.owner}/${CONFIG.repo}/contents/${path}`;
  const resp = await fetch(url, {
    method: "PUT",
    headers: ghHeaders(),
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(`GitHub write failed: ${resp.status} — ${err.message || ""}`);
  }
  return resp.json();
}

async function triggerWorkflow(projectId, action) {
  const url = `https://api.github.com/repos/${CONFIG.owner}/${CONFIG.repo}/dispatches`;
  const resp = await fetch(url, {
    method: "POST",
    headers: ghHeaders(),
    body: JSON.stringify({
      event_type: "planner_run",
      client_payload: {
        project_id: projectId,
        action,
        openrouter_key: openrouterKey,
      },
    }),
  });
  if (!resp.ok && resp.status !== 204) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(`Workflow trigger failed: ${resp.status} — ${err.message || ""}`);
  }
}

// ── Ensure data branch exists ─────────────────────────────────────────────

async function ensureDataBranch() {
  const url = `https://api.github.com/repos/${CONFIG.owner}/${CONFIG.repo}/branches/${CONFIG.dataBranch}`;
  const resp = await fetch(url, { headers: ghHeaders() });
  if (resp.ok) return;

  const mainResp = await fetch(
    `https://api.github.com/repos/${CONFIG.owner}/${CONFIG.repo}/git/refs/heads/main`,
    { headers: ghHeaders() }
  );
  const mainData = await mainResp.json();
  const mainSha = mainData.object.sha;

  await fetch(`https://api.github.com/repos/${CONFIG.owner}/${CONFIG.repo}/git/refs`, {
    method: "POST",
    headers: ghHeaders(),
    body: JSON.stringify({ ref: `refs/heads/${CONFIG.dataBranch}`, sha: mainSha }),
  });
}

// ── Project creation ──────────────────────────────────────────────────────

function generateProjectId() {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  const date = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}`;
  const time = `${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
  const rand = Math.random().toString(36).slice(2, 6);
  return `proj_${date}_${time}_${rand}`;
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
    project_id: projectId,
    status: "CREATED",
    ui_view: "PROGRESS_SPINNER",
    stage: "PROJECT_CREATED",
    updated_at: new Date().toISOString(),
    progress: { completed_steps: [], next_step: "FILES_PARSED" },
    error: null,
    artifacts: [],
  };

  await ghWriteFile(
    `projects/${projectId}/input.json`,
    JSON.stringify(input, null, 2)
  );
  await ghWriteFile(
    `projects/${projectId}/status.json`,
    JSON.stringify(initStatus, null, 2)
  );
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
    if (evtFile) {
      const evts = JSON.parse(evtFile.content);
      renderEvents(evts.events || []);
    }

    if (status.status === "COMPLETE") {
      stopPolling();
      await loadAndShowPlan();
    } else if (status.status === "BLOCKED_ON_HARD_DEPENDENCY") {
      stopPolling();
      showError(status.error);
    }
  } catch (e) {
    console.warn("Poll error:", e);
  }
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
  const nextStep = status.progress?.next_step;

  const list = document.getElementById("steps-list");
  list.innerHTML = "";
  for (const step of ALL_STEPS) {
    const li = document.createElement("li");
    li.textContent = STEP_LABELS[step] || step;
    if (completed.has(step)) {
      li.className = "done";
    } else if (nextStep === step) {
      li.className = "active";
    }
    list.appendChild(li);
  }

  if (status.status === "COMPLETE") {
    document.getElementById("spinner").style.display = "none";
    document.getElementById("status-text").textContent = "Complete ✓";
  }
}

function statusLabel(s) {
  const map = {
    CREATED: "Starting...",
    EXECUTING_COUNCIL: "Council running...",
    COMPLETE: "Complete",
    BLOCKED_ON_HARD_DEPENDENCY: "Blocked",
  };
  return map[s] || s;
}

function renderEvents(events) {
  const log = document.getElementById("events-log");
  log.innerHTML = events.slice(-30).reverse()
    .map((e) => `<div>${e.at.slice(11, 19)} ${e.message}</div>`)
    .join("");
}

function showError(error) {
  const box = document.getElementById("error-box");
  document.getElementById("error-msg").textContent = error?.message || "An error occurred.";
  box.style.display = "block";
  document.getElementById("spinner").style.display = "none";
}

async function loadAndShowPlan() {
  const file = await ghReadFile(`projects/${currentProjectId}/artifacts/plan.md`);
  if (!file) return;
  const section = document.getElementById("result-section");
  document.getElementById("plan-output").textContent = file.content;
  section.style.display = "block";
}

// ── Actions ───────────────────────────────────────────────────────────────

async function startRun() {
  const key = document.getElementById("or-key").value.trim();
  const prompt = document.getElementById("prompt-input").value.trim();
  const tok = document.getElementById("gh-token").value.trim();

  if (!tok) { alert("Please enter your GitHub token."); return; }
  if (!key) { alert("Please enter your OpenRouter API key."); return; }
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
    await new Promise((r) => setTimeout(r, 1500));
    await triggerWorkflow(currentProjectId, "start");

    btn.textContent = "Running...";
    startPolling();
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
  } catch (e) {
    alert(`Retry failed: ${e.message}`);
  }
}
