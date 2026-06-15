const state = {
  mode: "ask",
  pendingApproval: null,
  activeRunId: null,
  lastEventId: 0,
  pollTimer: null,
};

const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const error = new Error(typeof payload === "string" ? payload : payload.detail || "Request failed");
    error.status = response.status;
    error.payload = payload;
    throw error;
  }
  return payload;
}

function setText(id, value) {
  $(id).textContent = value;
}

function renderStatus(payload) {
  setText("userName", payload.user.display_name || payload.user.username);
  setText("authState", payload.auth.configured ? `Codex: ${payload.auth.auth_mode || "configured"}` : "Codex: login needed");
  setText("retentionDays", `${payload.settings.retention_days} days`);
  setText("liveSearch", payload.settings.enable_live_search ? "On" : "Off");

  const core = payload.home_assistant.core || {};
  const coreConfig = payload.home_assistant.core_config || {};
  const version = core.version || coreConfig.version || "unknown";
  setText("haVersion", `HA ${version}`);
  $("authPanel").hidden = Boolean(payload.auth.configured);
  renderRuns(payload.runs || []);
}

function renderRuns(runs) {
  const list = $("runsList");
  list.innerHTML = "";
  if (!runs.length) {
    list.innerHTML = '<p class="muted">No runs yet.</p>';
    return;
  }
  for (const run of runs) {
    const card = document.createElement("button");
    card.className = "run-card";
    card.type = "button";
    card.innerHTML = `
      <div>
        <strong>${escapeHtml(run.prompt)}</strong>
        <span>${run.mode} · ${run.risk_level} · ${run.status}</span>
      </div>
      <span>${new Date(run.started_at).toLocaleString()}</span>
    `;
    card.addEventListener("click", () => loadRun(run.id, true));
    list.appendChild(card);
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function appendEvent(event) {
  const out = $("runOutput");
  const empty = out.querySelector(".empty-state");
  if (empty) out.innerHTML = "";

  const div = document.createElement("div");
  div.className = "event";
  div.innerHTML = `<div class="event-type">${escapeHtml(event.type)}</div><code>${escapeHtml(event.payload)}</code>`;
  out.appendChild(div);
  out.scrollTop = out.scrollHeight;
}

function renderRun(run, events, reset = false) {
  if (reset) {
    $("runOutput").innerHTML = "";
    state.lastEventId = 0;
  }
  for (const event of events) {
    state.lastEventId = Math.max(state.lastEventId, event.id);
    appendEvent(event);
  }
  if (run.final_message && !document.querySelector(`[data-final-for="${run.id}"]`)) {
    const final = document.createElement("div");
    final.className = "final";
    final.dataset.finalFor = run.id;
    final.textContent = run.final_message;
    $("runOutput").appendChild(final);
  }
  if (run.diff && !document.querySelector(`[data-diff-for="${run.id}"]`)) {
    const diff = document.createElement("div");
    diff.className = "diff";
    diff.dataset.diffFor = run.id;
    diff.innerHTML = `<pre>${escapeHtml(run.diff)}</pre>`;
    $("runOutput").appendChild(diff);
  }
}

async function loadStatus() {
  const payload = await api("api/status");
  renderStatus(payload);
}

async function loadRun(runId, reset = false) {
  const payload = await api(`api/runs/${runId}?after_event_id=${reset ? 0 : state.lastEventId}`);
  state.activeRunId = runId;
  renderRun(payload.run, payload.events, reset);
  if (["queued", "running"].includes(payload.run.status)) {
    schedulePoll();
  }
  return payload.run;
}

function schedulePoll() {
  clearTimeout(state.pollTimer);
  state.pollTimer = setTimeout(async () => {
    if (state.activeRunId) {
      const run = await loadRun(state.activeRunId);
      if (!["queued", "running"].includes(run.status)) {
        await loadStatus();
      }
    }
  }, 1600);
}

async function submitRun(approved = false) {
  const prompt = $("prompt").value.trim();
  if (!prompt) return;

  const body = {
    prompt,
    mode: state.mode,
    approved,
    yolo: $("yolo").checked,
    secret_access_approved: $("secretApproved").checked,
  };

  $("approvalBox").hidden = true;
  try {
    const payload = await api("api/runs", {
      method: "POST",
      body: JSON.stringify(body),
    });
    state.pendingApproval = null;
    state.lastEventId = 0;
    $("runOutput").innerHTML = "";
    await loadRun(payload.run_id, true);
  } catch (error) {
    if (error.status === 409) {
      state.pendingApproval = body;
      const assessment = error.payload.detail.assessment;
      $("approvalText").textContent = `${assessment.warning} ${assessment.reasons.join(" ")}`;
      $("approvalBox").hidden = false;
      return;
    }
    alert(error.message);
  }
}

async function startLogin() {
  const payload = await api("api/auth/start", { method: "POST" });
  $("loginOutput").hidden = false;
  pollLogin(payload.job_id);
}

async function pollLogin(jobId) {
  const job = await api(`api/auth/jobs/${jobId}`);
  $("loginOutput").textContent = job.output || "Waiting for Codex login output...";
  if (job.status === "running") {
    setTimeout(() => pollLogin(jobId), 1200);
  } else {
    await loadStatus();
  }
}

function bind() {
  for (const button of document.querySelectorAll(".mode")) {
    button.addEventListener("click", () => {
      for (const item of document.querySelectorAll(".mode")) item.classList.remove("active");
      button.classList.add("active");
      state.mode = button.dataset.mode;
    });
  }

  $("composer").addEventListener("submit", (event) => {
    event.preventDefault();
    submitRun(false);
  });
  $("approveRun").addEventListener("click", () => submitRun(true));
  $("startLogin").addEventListener("click", startLogin);
  $("showImport").addEventListener("click", () => {
    $("importBox").hidden = !$("importBox").hidden;
  });
  $("importAuth").addEventListener("click", async () => {
    await api("api/auth/import", {
      method: "POST",
      body: JSON.stringify({ auth_json: $("authJson").value }),
    });
    $("authJson").value = "";
    await loadStatus();
  });
  $("refreshRuns").addEventListener("click", loadStatus);
}

bind();
loadStatus().catch((error) => {
  $("runOutput").innerHTML = `<div class="empty-state"><h2>Unable to load</h2><p>${escapeHtml(error.message)}</p></div>`;
});
