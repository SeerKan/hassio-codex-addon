const state = {
  mode: "ask",
  activeSessionId: null,
  pendingApproval: null,
  activeRunId: null,
  lastEventId: 0,
  pollTimer: null,
  sessions: [],
};

const SESSION_STORAGE_KEY = "codex_session_id";

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

function resolveSessionId(payload) {
  const persisted = localStorage.getItem(SESSION_STORAGE_KEY);
  const sessions = payload.sessions || [];
  if (persisted && sessions.some((session) => session.id === persisted)) {
    return persisted;
  }
  return payload.active_session_id;
}

async function renderStatus(payload) {
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

  state.sessions = payload.sessions || [];
  state.activeSessionId = resolveSessionId(payload);
  renderSessions();

  if (!state.activeSessionId && state.sessions.length) {
    state.activeSessionId = state.sessions[0].id;
  }

  if (state.activeSessionId) {
    const runsSessionId = payload.runs_session_id || payload.active_session_id;
    if (runsSessionId === state.activeSessionId && Array.isArray(payload.runs)) {
      renderRuns(payload.runs);
    } else {
      await refreshSessionRuns();
    }
  } else {
    renderRuns([]);
  }
}

function renderRuns(runs) {
  const list = $("runsList");
  list.innerHTML = "";
  if (!runs.length) {
    list.innerHTML = '<p class="muted">No runs yet.</p>';
    return;
  }
  for (const run of runs) {
    const preview = conciseText(run.prompt, 160);
    const started = new Date(run.started_at).toLocaleString();
    const card = document.createElement("button");
    card.className = "run-card";
    card.type = "button";
    card.title = run.prompt;
    card.innerHTML = `
      <div class="run-card-body">
        <strong class="run-prompt">${escapeHtml(preview)}</strong>
        <span class="run-meta">
          ${escapeHtml(run.mode)} · ${escapeHtml(run.risk_level)} · ${escapeHtml(run.status)}
          <span class="run-time">· ${escapeHtml(started)}</span>
        </span>
      </div>
    `;
    card.addEventListener("click", () => loadRun(run.id, true));
    list.appendChild(card);
  }
}

function renderSessions() {
  const select = $("sessionSelect");
  if (!select) return;

  select.innerHTML = "";
  if (!state.sessions.length) {
    const empty = document.createElement("option");
    empty.value = "";
    empty.textContent = "No sessions";
    select.appendChild(empty);
    select.value = "";
    select.disabled = true;
    state.activeSessionId = null;
    return;
  }

  select.disabled = false;
  for (const session of state.sessions) {
    const option = document.createElement("option");
    option.value = session.id;
    option.textContent = `${session.title} (${session.run_count})`;
    option.title = session.last_prompt || "";
    select.appendChild(option);
  }

  if (!state.activeSessionId || !state.sessions.some((session) => session.id === state.activeSessionId)) {
    state.activeSessionId = state.sessions[0].id;
  }

  select.value = state.activeSessionId;
  localStorage.setItem(SESSION_STORAGE_KEY, state.activeSessionId);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function renderMarkdown(value) {
  const lines = cleanTerminalText(value).split("\n");
  const html = [];
  let paragraph = [];
  let listType = "";
  let codeBlock = null;

  const closeParagraph = () => {
    if (!paragraph.length) return;
    html.push(`<p>${paragraph.map(renderInlineMarkdown).join("<br>")}</p>`);
    paragraph = [];
  };
  const closeList = () => {
    if (!listType) return;
    html.push(`</${listType}>`);
    listType = "";
  };

  for (const line of lines) {
    const fence = line.match(/^```/);
    if (fence) {
      if (codeBlock) {
        html.push(`<pre><code>${escapeHtml(codeBlock.join("\n"))}</code></pre>`);
        codeBlock = null;
      } else {
        closeParagraph();
        closeList();
        codeBlock = [];
      }
      continue;
    }

    if (codeBlock) {
      codeBlock.push(line);
      continue;
    }

    if (!line.trim()) {
      closeParagraph();
      closeList();
      continue;
    }

    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      closeParagraph();
      closeList();
      const level = heading[1].length + 2;
      html.push(`<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`);
      continue;
    }

    const unordered = line.match(/^\s*[-*]\s+(.+)$/);
    if (unordered) {
      closeParagraph();
      if (listType !== "ul") {
        closeList();
        html.push("<ul>");
        listType = "ul";
      }
      html.push(`<li>${renderInlineMarkdown(unordered[1])}</li>`);
      continue;
    }

    const ordered = line.match(/^\s*\d+[.)]\s+(.+)$/);
    if (ordered) {
      closeParagraph();
      if (listType !== "ol") {
        closeList();
        html.push("<ol>");
        listType = "ol";
      }
      html.push(`<li>${renderInlineMarkdown(ordered[1])}</li>`);
      continue;
    }

    const quote = line.match(/^\s*>\s?(.+)$/);
    if (quote) {
      closeParagraph();
      closeList();
      html.push(`<blockquote>${renderInlineMarkdown(quote[1])}</blockquote>`);
      continue;
    }

    closeList();
    paragraph.push(line);
  }

  closeParagraph();
  closeList();
  if (codeBlock) {
    html.push(`<pre><code>${escapeHtml(codeBlock.join("\n"))}</code></pre>`);
  }
  return html.join("");
}

function renderInlineMarkdown(value) {
  const codeSpans = [];
  let text = String(value).replace(/`([^`]+)`/g, (_match, code) => {
    const index = codeSpans.push(`<code>${escapeHtml(code)}</code>`) - 1;
    return `\u0000CODE${index}\u0000`;
  });

  text = escapeHtml(text)
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s<]+)\)/g, (_match, label, url) => {
      return `<a href="${url}" target="_blank" rel="noreferrer">${label}</a>`;
    })
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/__([^_]+)__/g, "<strong>$1</strong>")
    .replace(/\*([^*\n]+)\*/g, "<em>$1</em>");

  return text.replace(/\u0000CODE(\d+)\u0000/g, (_match, index) => codeSpans[Number(index)] || "");
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

function normalizeType(type) {
  return String(type || "")
    .trim()
    .replaceAll("_", ".")
    .toLowerCase();
}

function isItemEventType(type) {
  return ["item.started", "item.completed", "item.start", "item.complete"].includes(normalizeType(type));
}

function isCompletionEvent(type) {
  return ["item.completed", "item.complete", "turn.completed", "message.completed"].includes(
    normalizeType(type),
  );
}

function isNonItemPayloadEvent(type) {
  return [
    "error",
    "message.completed",
    "thread.started",
    "turn.completed",
    "turn.failed",
    "turn.started",
  ].includes(normalizeType(type));
}

function itemFromPayload(type, payload) {
  if (!payload || typeof payload !== "object") return {};
  if (payload.item && typeof payload.item === "object") return payload.item;
  if (isItemEventType(type)) return payload;
  return {};
}

function appendEvent(event) {
  const out = $("runOutput");
  const empty = out.querySelector(".empty-state");
  if (empty) out.innerHTML = "";

  const node = renderEvent(event);
  if (!node) return;
  appendRenderedNode(node);
  out.scrollTop = out.scrollHeight;
}

function appendRenderedNode(node) {
  if (node.classList.contains("activity")) {
    appendActivityNode(node);
    return;
  }
  const tray = $("runActivityTray");
  if (tray) {
    $("runOutput").insertBefore(node, tray);
    return;
  }
  $("runOutput").appendChild(node);
}

function appendActivityNode(node) {
  const tray = ensureActivityTray();
  tray.querySelector(".activity-list").appendChild(node);
  updateActivityCount();
}

function ensureActivityTray() {
  let tray = $("runActivityTray");
  if (tray) return tray;

  tray = document.createElement("details");
  tray.id = "runActivityTray";
  tray.className = "activity-tray";
  tray.innerHTML = `
    <summary>
      <span>Activity</span>
      <span id="activityCount">0 events</span>
    </summary>
    <div class="activity-list"></div>
  `;
  $("runOutput").appendChild(tray);
  return tray;
}

function updateActivityCount() {
  const countNode = $("activityCount");
  if (!countNode) return;
  const count = document.querySelectorAll("#runActivityTray .activity").length;
  countNode.textContent = `${count} ${count === 1 ? "event" : "events"}`;
}

function renderEvent(event) {
  if (event.display) {
    const rendered = renderDisplayEvent(event.display, event.type);
    if (rendered) return rendered;
  }

  const payload = parsePayload(event.payload);
  const eventType = normalizeType(event.type);

  if (eventType === "codex.command") {
    const argv = Array.isArray(payload.argv) ? payload.argv : [];
    return activityNode("Run started", commandPreview(argv), "activity-muted", commandDetails(argv));
  }

  if (eventType === "codex.stderr" || eventType === "codex.error") {
    const message = humanMessage(payload);
    if (/^Reading additional input from stdin/i.test(message)) {
      return activityNode("Prompt sent", "Codex received the request", "activity-muted");
    }
    return messageNode("Notice", message, "notice");
  }

  if (eventType.startsWith("backup.")) {
    return renderBackupEvent(eventType, payload);
  }

  if (typeof payload === "string") {
    return activityNode(labelForType(eventType), payload, "activity-muted");
  }

  const type = normalizeType(payload.type || eventType);
  if (isItemEventType(type) || (isItemEventType(eventType) && !isNonItemPayloadEvent(type))) {
    const itemEventType = isItemEventType(type) ? type : eventType;
    return renderItemEvent(itemEventType, itemFromPayload(itemEventType, payload));
  }

  if (type === "thread.started") {
    return activityNode("Session opened", shortId(payload.thread_id), "activity-muted");
  }
  if (type === "turn.started") {
    return activityNode("Working", "Thinking through the request", "activity-muted");
  }
  if (type === "turn.completed") {
    return activityNode("Done", usageSummary(payload.usage), "activity-muted");
  }
  if (type === "turn.failed") {
    return messageNode("Run failed", humanMessage(payload.error || payload), "notice");
  }
  if (type === "error") {
    return messageNode("Codex", humanMessage(payload), "notice");
  }
  return activityNode(labelForType(type), summarizeObject(payload), "activity-muted");
}

function renderDisplayEvent(display, fallbackType) {
  if (!display) return null;

  const title = display.title || labelForType(fallbackType);
  const summary = humanizeDisplayText(display.summary || "");
  const details = humanizeDetails(display.details || "");
  const kind = String(display.kind || "").toLowerCase();

  if (kind === "message") {
    return messageNode(title, summary || "(empty)", "assistant-message");
  }

  if (kind === "tool") {
    return activityNode(title, summary || "Tool event", "activity-tool", details);
  }

  if (kind === "notice") {
    return messageNode(title, summary || "Notice", "notice");
  }

  return activityNode(title, summary || "", "activity-muted", details);
}

function renderItemEvent(type, item) {
  const itemType = normalizeType(item.type || "item");
  const complete = isCompletionEvent(type);
  const text = extractItemText(item);

  if (isAssistantMessage(item)) {
    return messageNode("Answer", text || "(empty response)", "assistant-message");
  }

  if (itemType === "reasoning") {
    return activityNode(
      "Thinking",
      conciseText(text || (complete ? "Reasoning finished" : "Reasoning")),
      "activity-muted",
    );
  }

  if (isToolItem(itemType)) {
    const label = complete ? "Tool finished" : "Tool started";
    return activityNode(label, toolSummary(item), "activity-tool", toolDetails(item));
  }

  const label = complete ? `${labelForType(itemType)} completed` : `${labelForType(itemType)} started`;
  return activityNode(label, conciseText(text || summarizeObject(item) || "No details"), "activity-muted");
}

function renderBackupEvent(type, payload) {
  if (type === "backup.started") {
    return activityNode("Backup", `Creating ${payload.name || "pre-change backup"}`, "activity-tool");
  }
  if (type === "backup.completed") {
    return activityNode("Backup", `Created ${payload.slug || payload.name || "backup"}`, "activity-tool");
  }
  if (type === "backup.reused") {
    return activityNode("Backup", `Using existing ${payload.slug || payload.name || "backup"}`, "activity-muted");
  }
  if (type === "backup.failed") {
    return messageNode("Backup failed", humanMessage(payload), "notice");
  }
  return activityNode("Backup", summarizeObject(payload), "activity-muted");
}

function isAssistantMessage(item) {
  const type = normalizeType(item.type);
  return (
    type === "agent.message" ||
    (type === "message" && (!item.role || item.role === "assistant"))
  );
}

function isToolItem(type) {
  const normalized = normalizeType(type);
  return [
    "command.execution",
    "exec.command",
    "function.call",
    "local.shell.call",
    "mcp.tool.call",
    "shell.command",
    "tool.call",
    "web.search.call",
  ].includes(normalized);
}

function extractItemText(item) {
  if (typeof item.text === "string") return item.text;
  if (typeof item.output === "string") return item.output;
  if (typeof item.result === "string") return item.result;
  if (typeof item.aggregated_output === "string") return item.aggregated_output;
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
  article.dataset.messageKey = normalizeMessage(text);

  const header = document.createElement("div");
  header.className = "message-title";
  header.textContent = title;

  const body = document.createElement("div");
  body.className = "message-body markdown-body";
  body.innerHTML = renderMarkdown(text);

  article.append(header, body);
  return article;
}

function activityNode(title, summary, className, details = "") {
  const wrapper = document.createElement("details");
  wrapper.className = `activity ${className}`;
  const cleanSummary = humanizeDisplayText(summary);
  const cleanDetails = humanizeDetails(details);
  if (!cleanDetails) wrapper.classList.add("no-details");

  const summaryNode = document.createElement("summary");
  const titleNode = document.createElement("span");
  titleNode.textContent = title;
  const detailNode = document.createElement("span");
  detailNode.textContent = cleanSummary;
  summaryNode.append(titleNode, detailNode);
  wrapper.appendChild(summaryNode);

  if (cleanDetails) {
    const pre = document.createElement("pre");
    pre.textContent = cleanDetails;
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

function normalizeMessage(value) {
  return cleanTerminalText(value).replace(/\s+/g, " ").trim();
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
    .map(([key, item]) => {
      if (item && typeof item === "object") {
        if (!Array.isArray(item) && item.type) return `${key}: ${labelForType(item.type)}`;
        return `${key}: ${Array.isArray(item) ? "list" : "details"}`;
      }
      return `${key}: ${cleanTerminalText(item)}`;
    })
    .join(" · ");
}

function toolSummary(item) {
  if (item.command) {
    let base = "Shell command";
    const command = cleanTerminalText(item.command);
    if (command.includes("http://supervisor") || command.includes("/core/api") || command.includes("/backups")) {
      base = "Home Assistant API request";
    } else if (command.includes("curl")) {
      base = "Home Assistant HTTP request";
    }
    if (item.exit_code !== undefined && item.exit_code !== null) {
      return `${base} completed (exit code ${item.exit_code})`;
    }
    return base;
  }
  if (item.name) return conciseText(item.name, 160);
  if (item.tool) return conciseText(item.tool, 160);
  return labelForType(item.type || "tool call");
}

function toolDetails(item) {
  const parts = [];
  if (item.command) parts.push(`Command\n${cleanTerminalText(item.command)}`);
  if (item.name && !item.command) parts.push(`Tool\n${cleanTerminalText(item.name)}`);
  if (item.tool && !item.name) parts.push(`Tool\n${cleanTerminalText(item.tool)}`);
  const output = item.aggregated_output || item.output || item.result;
  if (typeof output === "string" && output.trim()) {
    parts.push(`Output\n${humanizeDetails(output)}`);
  }
  if (item.exit_code !== undefined && item.exit_code !== null) {
    parts.push(`Exit code\n${item.exit_code}`);
  }
  if (item.status) parts.push(`Status\n${item.status}`);
  return parts.join("\n\n");
}

function conciseText(value, maxLength = 220) {
  const text = cleanTerminalText(value).replace(/\s+/g, " ").trim();
  if (text.length <= maxLength) return text;
  return `${text.slice(0, maxLength - 1)}…`;
}

function humanizeDisplayText(value) {
  const text = cleanTerminalText(value).trim();
  if (!looksLikeJson(text)) return text;
  const parsed = parsePayload(text);
  if (!parsed || typeof parsed !== "object") return "Structured event";
  return humanMessage(parsed) || "Structured event";
}

function humanizeDetails(value) {
  const text = cleanTerminalText(value).trim();
  if (!text) return "";
  if (!looksLikeJson(text)) return text;
  return "Structured output omitted";
}

function looksLikeJson(value) {
  const text = cleanTerminalText(value).trim();
  if (!text) return false;
  if (!((text.startsWith("{") && text.endsWith("}")) || (text.startsWith("[") && text.endsWith("]")))) {
    return false;
  }
  try {
    JSON.parse(text);
    return true;
  } catch {
    try {
      JSON.parse(text.replaceAll('\\"', '"'));
      return true;
    } catch {
      return false;
    }
  }
}

function usageSummary(usage) {
  if (!usage || typeof usage !== "object") return "Completed";
  const input = usage.input_tokens ?? usage.total_input_tokens;
  const output = usage.output_tokens ?? usage.total_output_tokens;
  if (input && output) return `${input.toLocaleString()} input tokens · ${output.toLocaleString()} output tokens`;
  return "Completed";
}

function appendFinalAnswer(run) {
  if (!run.final_message) return;
  const normalized = normalizeMessage(run.final_message);
  const existing = [...document.querySelectorAll(".assistant-message")].some(
    (node) => node.dataset.messageKey === normalized,
  );
  if (existing || document.querySelector(`[data-final-for="${run.id}"]`)) return;

  const final = messageNode("Answer", run.final_message, "assistant-message");
  final.dataset.finalFor = run.id;
  appendRenderedNode(final);
}

function appendDiff(run) {
  if (!run.diff || document.querySelector(`[data-diff-for="${run.id}"]`)) return;
  const diff = document.createElement("details");
  diff.className = "activity activity-tool";
  diff.dataset.diffFor = run.id;
  diff.innerHTML = "<summary><span>Changes</span><span>Review the generated diff</span></summary>";
  const pre = document.createElement("pre");
  pre.textContent = run.diff;
  diff.appendChild(pre);
  appendActivityNode(diff);
}

function setRunState(text) {
  const toolbar = $("runToolbar");
  if (!toolbar) return;
  toolbar.hidden = false;
  setText("runState", text);
}

function setRunButtonBusy(busy, label = "Run Codex") {
  const button = $("runButton");
  button.disabled = busy;
  button.textContent = busy ? label : "Run Codex";
}

function setEmptyState(title, message) {
  $("runOutput").innerHTML = `
    <div class="empty-state">
      <h2>${escapeHtml(title)}</h2>
      <p>${escapeHtml(message)}</p>
    </div>
  `;
}

function showStartingState(title, message) {
  setRunState(title);
  setEmptyState(title, message);
}

function setAllActivityOpen(open) {
  const tray = $("runActivityTray");
  if (tray) tray.open = open;
  for (const item of document.querySelectorAll("#runOutput details.activity:not(.no-details)")) {
    item.open = open;
  }
}

function runStatusText(run) {
  if (!run) return "Ready";
  if (run.status === "queued") return "Queued";
  if (run.status === "running") return "Running";
  if (run.status === "completed") return "Completed";
  if (run.status === "failed") return "Failed";
  return labelForType(run.status || "ready");
}

function renderRun(run, events, reset = false) {
  if (reset) {
    $("runOutput").innerHTML = "";
    state.lastEventId = 0;
  }
  setRunState(runStatusText(run));
  for (const event of events) {
    state.lastEventId = Math.max(state.lastEventId, event.id);
    appendEvent(event);
  }
  appendFinalAnswer(run);
  appendDiff(run);
}

async function loadStatus() {
  const payload = await api("api/status");
  await renderStatus(payload);
}

async function refreshSessionRuns() {
  if (!state.activeSessionId) {
    renderRuns([]);
    return;
  }

  const query = `api/runs?session_id=${encodeURIComponent(state.activeSessionId)}`;
  const payload = await api(query);
  renderRuns(payload.runs || []);
}

function activateSession(sessionId) {
  if (!sessionId) {
    state.activeSessionId = null;
    localStorage.removeItem(SESSION_STORAGE_KEY);
    renderRuns([]);
    return;
  }

  state.activeSessionId = sessionId;
  localStorage.setItem(SESSION_STORAGE_KEY, sessionId);
  if ($("sessionSelect")) {
    $("sessionSelect").value = sessionId;
  }
}

async function startNewSession() {
  const button = $("newSession");
  button.disabled = true;
  button.textContent = "Creating...";
  showStartingState("Creating new session", "Preparing a clean conversation context.");
  try {
    const payload = await api("api/sessions", {
      method: "POST",
      body: JSON.stringify({}),
    });
    activateSession(payload.session_id);
    await loadStatus();
    activateSession(payload.session_id);
    renderRuns([]);
    setRunState("New session ready");
    setEmptyState("New session ready", "Send a prompt to start this conversation.");
    $("prompt").focus();
  } catch (error) {
    setRunState("Session failed");
    setEmptyState("Could not create session", error.message);
  } finally {
    button.disabled = false;
    button.textContent = "New session";
  }
}

async function loadRun(runId, reset = false) {
  const payload = await api(`api/runs/${runId}?after_event_id=${reset ? 0 : state.lastEventId}`);
  state.activeRunId = runId;
  if (payload.run.session_id && payload.run.session_id !== state.activeSessionId) {
    activateSession(payload.run.session_id);
  }
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
    session_id: state.activeSessionId,
    create_new_session: false,
  };

  $("approvalBox").hidden = true;
  setRunButtonBusy(true, "Starting...");
  showStartingState("Starting Codex", "Creating the run and opening the session.");
  try {
    const payload = await api("api/runs", {
      method: "POST",
      body: JSON.stringify(body),
    });
    state.pendingApproval = null;
    state.lastEventId = 0;
    if (payload.session_id) {
      activateSession(payload.session_id);
      await loadStatus();
    }
    showStartingState("Run started", "Waiting for the first response.");
    await loadRun(payload.run_id, true);
  } catch (error) {
    if (error.status === 409) {
      state.pendingApproval = body;
      const assessment = error.payload.detail.assessment;
      $("approvalText").textContent = `${assessment.warning} ${assessment.reasons.join(" ")}`;
      $("approvalBox").hidden = false;
      setRunState("Approval required");
      setEmptyState("Approval required", "Review the warning above, then approve the run if it looks right.");
      return;
    }
    setRunState("Run failed");
    setEmptyState("Could not start run", error.message);
  } finally {
    setRunButtonBusy(false);
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
  $("sessionSelect").addEventListener("change", async (event) => {
    const sessionId = event.target.value || null;
    activateSession(sessionId);
    await refreshSessionRuns();
    $("runOutput").innerHTML = `<div class="empty-state"><h2>Conversation selected</h2><p>Select a run from this session or start a new one.</p></div>`;
  });
  $("newSession").addEventListener("click", async () => {
    await startNewSession();
  });
  $("refreshRuns").addEventListener("click", loadStatus);
  $("openAllActivity").addEventListener("click", () => setAllActivityOpen(true));
  $("closeAllActivity").addEventListener("click", () => setAllActivityOpen(false));
}

bind();
loadStatus().catch((error) => {
  $("runOutput").innerHTML = `<div class="empty-state"><h2>Unable to load</h2><p>${escapeHtml(error.message)}</p></div>`;
});
