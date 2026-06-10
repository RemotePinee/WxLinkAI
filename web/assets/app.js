const $ = (id) => document.getElementById(id);

const ui = {
  auth: $("authKey"),
  load: $("loadBtn"),
  logout: $("logoutBtn"),
  refresh: $("refreshBtn"),
  save: $("saveBtn"),
  format: $("formatBtn"),
  status: $("statusPill"),
  message: $("messageLine"),
  editor: $("configEditor"),
  sessions: $("sessionsCount"),
  images: $("imagesCount"),
  routing: $("routingMode"),
  ttl: $("imageTtl"),
  recent: $("recentSessions"),
  searchEnabled: $("searchEnabled"),
  searchBaseUrl: $("searchBaseUrl"),
  searchTimeout: $("searchTimeout"),
  searchMax: $("searchMax"),
  terminalStream: $("terminalStream"),
  terminalState: $("terminalState"),
  terminalClear: $("terminalClearBtn"),
};

const tabs = [...document.querySelectorAll(".tab[data-tab]")];
const providerPanels = [...document.querySelectorAll(".provider-panel[data-provider]")];
const providerForms = providerPanels.filter((panel) => panel.tagName.toLowerCase() === "form");
const AUTH_STORAGE_KEY = "wxlinkai-auth-key";
const CONFIG_STORAGE_KEY = "wxlinkai-config-cache";
const STATUS_STORAGE_KEY = "wxlinkai-status-cache";
const TERMINAL_STORAGE_KEY = "wxlinkai-terminal-cache";
const LEGACY_STORAGE_KEYS = {
  [AUTH_STORAGE_KEY]: "wechat-bridge-auth-key",
  [CONFIG_STORAGE_KEY]: "wechat-bridge-config-cache",
  [STATUS_STORAGE_KEY]: "wechat-bridge-status-cache",
  [TERMINAL_STORAGE_KEY]: "wechat-bridge-terminal-cache",
};
let terminalSeq = 0;
let terminalTimer = null;
let terminalLines = [];

function migrateStorageKeys() {
  try {
    for (const [nextKey, legacyKey] of Object.entries(LEGACY_STORAGE_KEYS)) {
      const legacyValue = window.localStorage.getItem(legacyKey);
      if (legacyValue && !window.localStorage.getItem(nextKey)) {
        window.localStorage.setItem(nextKey, legacyValue);
      }
    }
  } catch {
    // localStorage may be unavailable in a locked-down WebView.
  }
}

migrateStorageKeys();

function token() {
  return ui.auth.value.trim();
}

function restoreToken() {
  try {
    ui.auth.value = window.localStorage.getItem(AUTH_STORAGE_KEY) || "";
  } catch {
    ui.auth.value = "";
  }
}

function persistToken() {
  try {
    const value = token();
    if (value) {
      window.localStorage.setItem(AUTH_STORAGE_KEY, value);
    } else {
      window.localStorage.removeItem(AUTH_STORAGE_KEY);
    }
  } catch {
    // localStorage may be unavailable in a locked-down WebView.
  }
}

function storageGet(key, fallback = null) {
  try {
    const value = window.localStorage.getItem(key);
    return value ? JSON.parse(value) : fallback;
  } catch {
    return fallback;
  }
}

function storageSet(key, value) {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Ignore storage failures in restricted WebViews.
  }
}

function storageRemove(...keys) {
  try {
    for (const key of keys) window.localStorage.removeItem(key);
  } catch {
    // Ignore storage failures in restricted WebViews.
  }
}

function requestHeaders() {
  return {
    "Content-Type": "application/json",
    "Authorization": `Bearer ${token()}`,
  };
}

function say(text, type = "") {
  ui.message.textContent = text;
  ui.message.className = `message ${type}`.trim();
}

function setTerminalState(text, type = "") {
  ui.terminalState.textContent = text;
  ui.terminalState.className = `badge ${type}`.trim();
}

function markPending(statusText = "恢复连接", terminalText = "同步中") {
  ui.status.textContent = statusText;
  ui.status.classList.remove("ok");
  ui.status.classList.add("pending");
  setTerminalState(terminalText, "pending");
}

function markConnected(ok) {
  ui.status.textContent = ok ? "已连接" : "未连接";
  ui.status.classList.remove("pending");
  ui.status.classList.toggle("ok", ok);
  setTerminalState(ok ? "在线" : "等待连接", ok ? "" : "muted");
}

function asTime(ts) {
  const value = Number(ts || 0);
  if (!value) return "-";
  return new Date(value * 1000).toLocaleString();
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;",
  })[ch]);
}

function showTab(name) {
  for (const tab of tabs) {
    tab.classList.toggle("active", tab.dataset.tab === name);
  }
  for (const panel of providerPanels) {
    panel.classList.toggle("active", panel.dataset.provider === name);
  }
}

function formFor(name) {
  return providerForms.find((form) => form.dataset.provider === name);
}

function fillForm(name, data = {}) {
  const form = formFor(name);
  if (!form) return;
  for (const input of form.querySelectorAll("input[name]")) {
    input.value = data[input.name] ?? "";
  }
}

function readForm(name) {
  const form = formFor(name);
  const data = {};
  if (!form) return data;
  for (const input of form.querySelectorAll("input[name]")) {
    data[input.name] = input.value.trim();
  }
  return data;
}

function bindConfig(config) {
  fillForm("chat", config.chat || {});
  fillForm("intent", config.intent || {});
  fillForm("image", config.image || {});
  ui.searchEnabled.checked = !!config.search?.enabled;
  ui.searchBaseUrl.value = config.search?.base_url || "";
  ui.searchTimeout.value = config.search?.timeout_seconds || 12;
  ui.searchMax.value = config.search?.max_results || 5;
}

function configFromEditor() {
  return JSON.parse(ui.editor.value);
}

function collectConfig() {
  const config = configFromEditor();
  config.chat = { ...(config.chat || {}), ...readForm("chat") };
  config.intent = { ...(config.intent || {}), ...readForm("intent") };
  config.image = { ...(config.image || {}), ...readForm("image") };
  config.search = {
    ...(config.search || {}),
    enabled: ui.searchEnabled.checked,
    base_url: ui.searchBaseUrl.value.trim(),
    timeout_seconds: Number(ui.searchTimeout.value || 12),
    max_results: Number(ui.searchMax.value || 5),
  };
  return config;
}

function clearProviderForms() {
  for (const form of providerForms) {
    for (const input of form.querySelectorAll("input[name]")) {
      input.value = "";
    }
  }
  ui.searchEnabled.checked = false;
  ui.searchBaseUrl.value = "";
  ui.searchTimeout.value = "";
  ui.searchMax.value = "";
  ui.editor.value = "";
}

function clearStatusViews() {
  ui.sessions.textContent = "-";
  ui.images.textContent = "-";
  ui.routing.textContent = "-";
  ui.ttl.textContent = "-";
  ui.recent.innerHTML = `<div class="empty">连接后显示最近会话。</div>`;
}

async function apiGet(path) {
  const res = await fetch(path, { headers: requestHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

async function loadConfig() {
  const data = await apiGet("/api/ui/config");
  ui.editor.value = JSON.stringify(data.config, null, 2);
  bindConfig(data.config || {});
  storageSet(CONFIG_STORAGE_KEY, data.config || {});
}

function renderRecentSessions(items = []) {
  if (!items.length) {
    ui.recent.innerHTML = `<div class="empty">暂无会话。</div>`;
    return;
  }

  ui.recent.innerHTML = items.map((item) => {
    const key = escapeHtml(item.key || "");
    const count = Number(item.history_count ?? 0);
    const updated = escapeHtml(asTime(item.updated_at));
    return `
      <div class="session-item">
        <div>
          <b>${key}</b>
          <span>${count} 条历史</span>
        </div>
        <div class="session-meta">${updated}</div>
      </div>
    `;
  }).join("");
}

async function loadStatus() {
  const data = await apiGet("/api/ui/status");
  markConnected(true);
  ui.sessions.textContent = data.sessions ?? "-";
  ui.images.textContent = data.images ?? "-";
  ui.routing.textContent = data.routing_mode || "-";
  ui.ttl.textContent = data.image_ttl_seconds ? `${data.image_ttl_seconds}s` : "-";
  renderRecentSessions(data.recent_sessions || []);
  storageSet(STATUS_STORAGE_KEY, data);
}

function resetConnection() {
  terminalSeq = 0;
  terminalLines = [];
  renderTerminal();
  stopTerminalPolling();
  markConnected(false);
}

function logout() {
  stopTerminalPolling();
  terminalSeq = 0;
  terminalLines = [];
  ui.auth.value = "";
  document.documentElement.classList.remove("has-auth-cache");
  storageRemove(AUTH_STORAGE_KEY, CONFIG_STORAGE_KEY, STATUS_STORAGE_KEY, TERMINAL_STORAGE_KEY);
  clearProviderForms();
  clearStatusViews();
  markConnected(false);
  say("已退出，请重新输入 auth_key。");
  renderTerminal();
  showTab("chat");
}

function renderTerminal() {
  if (!terminalLines.length) {
    const text = token() ? "正在同步后端最近事件。" : "等待连接后开始接收事件。";
    ui.terminalStream.innerHTML = `<div class="terminal-line dim">${text}</div>`;
    return;
  }
  ui.terminalStream.innerHTML = terminalLines.map((item) => {
    const time = new Date(item.ts * 1000).toLocaleTimeString();
    return `<div class="terminal-line ${escapeHtml(item.level)}"><span>${escapeHtml(time)}</span><b>${escapeHtml(item.level)}</b><code>${escapeHtml(item.message)}</code></div>`;
  }).join("");
  ui.terminalStream.scrollTop = ui.terminalStream.scrollHeight;
}

function restoreCachedConfig() {
  const config = storageGet(CONFIG_STORAGE_KEY);
  if (!config || typeof config !== "object") return false;
  ui.editor.value = JSON.stringify(config, null, 2);
  bindConfig(config);
  return true;
}

function restoreCachedStatus() {
  const data = storageGet(STATUS_STORAGE_KEY);
  if (!data || typeof data !== "object") return false;
  markConnected(true);
  ui.sessions.textContent = data.sessions ?? "-";
  ui.images.textContent = data.images ?? "-";
  ui.routing.textContent = data.routing_mode || "-";
  ui.ttl.textContent = data.image_ttl_seconds ? `${data.image_ttl_seconds}s` : "-";
  renderRecentSessions(data.recent_sessions || []);
  return true;
}

function restoreCachedTerminal() {
  const data = storageGet(TERMINAL_STORAGE_KEY);
  if (!data || typeof data !== "object") return false;
  terminalSeq = Number(data.seq || 0);
  terminalLines = Array.isArray(data.lines) ? data.lines.slice(-300) : [];
  renderTerminal();
  if (terminalLines.length) setTerminalState("在线");
  return terminalLines.length > 0;
}

async function pollTerminal() {
  if (!token()) return;
  try {
    const data = await apiGet(`/api/ui/logs?after=${terminalSeq}&limit=80`);
    const events = Array.isArray(data.events) ? data.events : [];
    if (events.length) {
      terminalSeq = Math.max(terminalSeq, ...events.map((item) => Number(item.seq || 0)));
      terminalLines = [...terminalLines, ...events].slice(-300);
      renderTerminal();
      storageSet(TERMINAL_STORAGE_KEY, { seq: terminalSeq, lines: terminalLines });
    }
    setTerminalState("在线");
  } catch (err) {
    setTerminalState("终端离线", "muted");
    if (!terminalLines.length) {
      ui.terminalStream.innerHTML = `<div class="terminal-line error">终端读取失败：${escapeHtml(err.message || err)}</div>`;
    }
  }
}

function startTerminalPolling() {
  stopTerminalPolling();
  terminalTimer = window.setInterval(() => {
    pollTerminal();
  }, 2000);
  pollTerminal();
}

function stopTerminalPolling() {
  if (terminalTimer) {
    window.clearInterval(terminalTimer);
    terminalTimer = null;
  }
}

async function connect(options = {}) {
  if (!token()) {
    markConnected(false);
    say("输入 auth_key 后连接。", "error");
    return;
  }
  persistToken();
  await loadConfig();
  await loadStatus();
  startTerminalPolling();
  say("控制台已连接。", "ok");
}

tabs.forEach((tab) => {
  tab.addEventListener("click", () => showTab(tab.dataset.tab));
});

restoreToken();
showTab("chat");
const bootHasToken = !!token();
let bootHasDataCache = false;
if (bootHasToken) {
  const hasConfigCache = restoreCachedConfig();
  const hasStatusCache = restoreCachedStatus();
  const hasTerminalCache = restoreCachedTerminal();
  bootHasDataCache = hasConfigCache || hasStatusCache || hasTerminalCache;
  markConnected(true);
  if (!hasTerminalCache) renderTerminal();
  say("控制台已连接。", "ok");
} else {
  markConnected(false);
  say("输入 auth_key 后连接。");
  renderTerminal();
}

ui.load.addEventListener("click", () => {
  if (token()) {
    say("正在连接后台。");
  }
  connect().catch((err) => {
    markConnected(false);
    say(`连接失败：${err.message || err}`, "error");
  });
});

ui.refresh.addEventListener("click", () => {
  if (!token()) {
    markConnected(false);
    say("输入 auth_key 后刷新。", "error");
    return;
  }
  persistToken();
  markPending("刷新状态", "同步中");
  Promise.all([loadConfig(), loadStatus(), pollTerminal()])
    .then(() => {
      markConnected(true);
      startTerminalPolling();
      say("状态已刷新。", "ok");
    })
    .catch((err) => say(`刷新失败：${err.message || err}`, "error"));
});

ui.logout.addEventListener("click", logout);

ui.format.addEventListener("click", () => {
  try {
    const config = configFromEditor();
    ui.editor.value = JSON.stringify(config, null, 2);
    bindConfig(config);
    say("JSON 已整理。", "ok");
    showTab("raw");
  } catch {
    say("JSON 格式不对。", "error");
  }
});

ui.save.addEventListener("click", async () => {
  try {
    const config = collectConfig();
    const res = await fetch("/api/ui/config", {
      method: "POST",
      headers: requestHeaders(),
      body: JSON.stringify({ config }),
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    if (config.auth_key) {
      ui.auth.value = String(config.auth_key);
      persistToken();
    }
    ui.editor.value = JSON.stringify(config, null, 2);
    storageSet(CONFIG_STORAGE_KEY, config);
    say(data.message || "配置已保存并热加载。", "ok");
    await pollTerminal();
  } catch (err) {
    say(`保存失败：${err.message || err}`, "error");
  }
});

ui.terminalClear.addEventListener("click", () => {
  terminalLines = [];
  storageSet(TERMINAL_STORAGE_KEY, { seq: terminalSeq, lines: terminalLines });
  renderTerminal();
});

ui.auth.addEventListener("keydown", (ev) => {
  if (ev.key === "Enter") ui.load.click();
});

ui.auth.addEventListener("input", persistToken);

window.addEventListener("beforeunload", stopTerminalPolling);

connect({ silent: bootHasToken }).catch((err) => {
  stopTerminalPolling();
  if (bootHasToken || bootHasDataCache) {
    say(`后台刷新失败：${err.message || err}`, "error");
    return;
  }
  markConnected(false);
});
