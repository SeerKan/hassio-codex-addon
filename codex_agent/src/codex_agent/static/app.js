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
  if (payload.auth.configured) {
    setText("authState", `Codex: ${payload.auth.auth_mode || "configured"}`);
  } else if (payload.auth.error) {
    setText("authState", "Codex: auth invalid");
  } else {
    setText("authState", "Codex: login needed");
  }
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

function cleanTerminalText(value) {
  return String(value || "")
    .replace(/\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1B\\))/g, "")
    .replace(/[\x00-\x08\x0b-\x1f\x7f]/g, "")
    .replace(/\r/g, "");
}

function parsePayload(payload) {
  if (payload && typeof payload === "object") return payload;
  try {
    return JSON.parse(payload);
  } catch {
    return cleanTerminalText(payload);
  }
}

function appendEvent(event) {
  const out = $("runOutput");
  const empty = out.querySelector(".empty-state");
  if (empty) out.innerHTML = "";

  const node = renderEvent(event);
  if (!node) return;
  out.appendChild(node);
  out.scrollTop = out.scrollHeight;
}

function renderEvent(event) {
  const payload = parsePayload(event.payload);

  if (event.type === "codex.command") {
    const argv = Array.isArray(payload.argv) ? payload.argv : [];
    return activityNode("Run started", commandPreview(argv), "activity-muted", commandDetails(argv));
  }

  if (event.type === "codex.stderr" || event.type === "codex.error") {
    return messageNode("Notice", humanMessage(payload), "notice");
  }

  if (typeof payload === "string") {
    return activityNode(labelForType(event.type), payload, "activity-muted");
  }

  const type = payload.type || event.type;
  if (type === "thread.started") {
    return activityNode("Session opened", shortId(payload.thread_id), "activity-muted");
  }
  if (type === "turn.started") {
    return activityNode("Working", "Thinking through the request", "activity-muted");
  }
  if (type === "turn.failed") {
    return messageNode("Run failed", humanMessage(payload.error || payload), "notice");
  }
  if (type === "error") {
    return messageNode("Codex", humanMessage(payload), "notice");
  }
  if (type === "item.started" || type === "item.completed") {
    return renderItemEvent(type, payload.item || {});
  }

  return activityNode(labelForType(type), summarizeObject(payload), "activity-muted", prettyJson(payload));
}

function renderItemEvent(type, item) {
  const itemType = item.type || "item";
  const complete = type === "item.completed";
  const text = extractItemText(item);

  if (isAssistantMessage(item)) {
    return messageNode("Codex", text || "(empty response)", "assistant-message");
  }

  if (itemType === "reasoning") {
    return activityNode("Thinking", text || (complete ? "Reasoning finished" : "Reasoning"), "activity-muted");
  }

  if (isToolItem(itemType)) {
    const label = complete ? "Tool finished" : "Tool started";
    return activityNode(label, toolSummary(item), "activity-tool", text || prettyJson(item));
  }

  return activityNode(labelForType(itemType), text || summarizeObject(item), "activity-muted", prettyJson(item));
}

function isAssistantMessage(item) {
  return (
    item.type === "agent_message" ||
    (item.type === "message" && (!item.role || item.role === "assistant"))
  );
}

function isToolItem(type) {
  return [
    "command_execution",
    "exec_command",
    "function_call",
    "local_shell_call",
    "mcp_tool_call",
    "shell_command",
    "tool_call",
    "web_search_call",
  ].includes(type);
}

function extractItemText(item) {
  if (typeof item.text === "string") return item.text;
  if (typeof item.output === "string") return item.output;
  if (typeof item.result === "string") return item.result;
  return extractContentText(item.content) || extractContentText(item.summary);
}

function extractContentText(content) {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .map((entry) => {
      if (typeof entry === "string") return entry;
      if (!entry || typeof entry !== "object") return "";
      return entry.text || entry.content || entry.summary || "";
    })
    .filter(Boolean)
    .join("\n");
}

function messageNode(title, text, className) {
  const article = document.createElement("article");
  article.className = `message ${className}`;

  const header = document.createElement("div");
  header.className = "message-title";
  header.textContent = title;

  const body = document.createElement("div");
  body.className = "message-body";
  body.textContent = cleanTerminalText(text);

  article.append(header, body);
  return article;
}

function activityNode(title, summary, className, details = "") {
  const wrapper = document.createElement("details");
  wrapper.className = `activity ${className}`;
  if (!details) wrapper.classList.add("no-details");

  const summaryNode = document.createElement("summary");
  const titleNode = document.createElement("span");
  titleNode.textContent = title;
  const detailNode = document.createElement("span");
  detailNode.textContent = cleanTerminalText(summary);
  summaryNode.append(titleNode, detailNode);
  wrapper.appendChild(summaryNode);

  if (details) {
    const pre = document.createElement("pre");
    pre.textContent = cleanTerminalText(details);
    wrapper.appendChild(pre);
  }
  return wrapper;
}

function commandPreview(argv) {
  if (!argv.length) return "Preparing command";
  const parts = argv.filter((part) => part !== "<prompt>");
  return parts.slice(0, 6).join(" ");
}

function commandDetails(argv) {
  return argv
    .map((part, index) => `${String(index + 1).padStart(2, "0")}  ${part}`)
    .join("\n");
}

function labelForType(type) {
  return String(type || "event")
    .replace(/^codex\./, "")
    .replaceAll(".", " ")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function shortId(value) {
  if (!value) return "";
  const text = String(value);
  return text.length > 16 ? `${text.slice(0, 8)}…${text.slice(-6)}` : text;
}

function humanMessage(value) {
  if (typeof value === "string") return value;
  if (!value || typeof value !== "object") return String(value || "");
  return value.message || value.error || summarizeObject(value);
}

function summarizeObject(value) {
  if (!value || typeof value !== "object") return String(value || "");
  if (value.name) return String(value.name);
  if (value.command) return String(value.command);
  if (value.status) return String(value.status);
  return Object.entries(value)
    .slice(0, 4)
    .map(([key, item]) => `${key}: ${typeof item === "object" ? JSON.stringify(item) : item}`)
    .join(" · ");
}

function toolSummary(item) {
  return item.name || item.command || item.tool || item.type || "Tool call";
}

function prettyJson(value) {
  return JSON.stringify(value, null, 2);
}

function appendFinalAnswer(run) {
  if (!run.final_message) return;
  const existing = [...document.querySelectorAll(".assistant-message .message-body")].some(
    (node) => node.textContent.trim() === run.final_message.trim(),
  );
  if (existing || document.querySelector(`[data-final-for="${run.id}"]`)) return;

  const final = messageNode("Codex", run.final_message, "assistant-message");
  final.dataset.finalFor = run.id;
  $("runOutput").appendChild(final);
}

function appendDiff(run) {
  if (!run.diff || document.querySelector(`[data-diff-for="${run.id}"]`)) return;
  const diff = document.createElement("details");
  diff.className = "activity activity-tool";
  diff.dataset.diffFor = run.id;
  diff.open = true;
  diff.innerHTML = "<summary><span>Changes</span><span>Review the generated diff</span></summary>";
  const pre = document.createElement("pre");
  pre.textContent = run.diff;
  diff.appendChild(pre);
  $("runOutput").appendChild(diff);
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
  appendFinalAnswer(run);
  appendDiff(run);
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
  renderLoginJob({ status: "running", output: "Waiting for Codex login output..." });
  pollLogin(payload.job_id);
}

async function pollLogin(jobId) {
  const job = await api(`api/auth/jobs/${jobId}`);
  renderLoginJob(job);
  if (job.status === "running") {
    setTimeout(() => pollLogin(jobId), 1200);
  } else {
    await loadStatus();
  }
}

function renderLoginJob(job) {
  const panel = $("loginOutput");
  panel.hidden = false;
  panel.innerHTML = "";

  if (job.login_url || job.device_code) {
    const card = document.createElement("div");
    card.className = "login-card";
    if (job.login_url) {
      const link = document.createElement("a");
      link.href = job.login_url;
      link.target = "_blank";
      link.rel = "noreferrer";
      link.textContent = job.login_url;
      card.appendChild(loginField("Open", link));
    }
    if (job.device_code) {
      const code = document.createElement("button");
      code.type = "button";
      code.className = "code-button";
      code.textContent = job.device_code;
      code.addEventListener("click", () => copyText(job.device_code));
      card.appendChild(loginField("Code", code));
    }
    panel.appendChild(card);
  }

  const output = document.createElement("pre");
  output.className = "terminal";
  output.textContent = cleanTerminalText(job.output || "Waiting for Codex login output...");
  panel.appendChild(output);
}

function loginField(label, valueNode) {
  const row = document.createElement("div");
  row.className = "login-field";
  const labelNode = document.createElement("span");
  labelNode.textContent = label;
  row.append(labelNode, valueNode);
  return row;
}

async function copyText(value) {
  try {
    await navigator.clipboard.writeText(value);
  } catch {
    const area = document.createElement("textarea");
    area.value = value;
    document.body.appendChild(area);
    area.select();
    document.execCommand("copy");
    area.remove();
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
