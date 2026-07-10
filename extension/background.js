// Background service worker: owns the WebSocket to the agent, so tasks keep
// running when the popup is closed. The popup is a pure view: it connects a
// Port, receives log entries and sends commands (run / answer / cancel / clear).
// Server pings every 15s keep this worker alive during long agent steps.

const WS_URL = "ws://localhost:8001/ws";
const MAX_LOG_ENTRIES = 500;

let ws = null;
let running = false;
let popupPort = null;
let sessionId = null;
let logHistory = null; // null = not loaded from storage yet

// ── State (chrome.storage.session: survives popup close, dies with browser) ──

async function loadState() {
  if (logHistory !== null) return;
  const s = await chrome.storage.session.get(["logHistory", "sessionId", "running"]);
  logHistory = s.logHistory || [];
  sessionId = s.sessionId || crypto.randomUUID();
  if (s.running && !running) {
    // The worker was killed mid-task: the WS died with it, the run aborted.
    pushEntry({
      text: "Задача была прервана (фоновый процесс перезапущен). Контекст диалога сохранён.",
      action: "", isError: true,
    });
  }
  await chrome.storage.session.set({ sessionId, running });
}

function pushEntry(entry) {
  logHistory.push(entry);
  if (logHistory.length > MAX_LOG_ENTRIES) {
    logHistory = logHistory.slice(-MAX_LOG_ENTRIES);
  }
  chrome.storage.session.set({ logHistory });
  if (popupPort) popupPort.postMessage({ type: "log", entry });
}

function setRunning(val) {
  running = val;
  chrome.storage.session.set({ running: val });
  if (popupPort) popupPort.postMessage({ type: "state", running: val });
}

// ── Notifications (only when the popup is closed) ────────────────────────────

function notify(title, message) {
  if (popupPort) return;
  chrome.notifications.create({
    type: "basic",
    iconUrl: "icon128.png",
    title,
    message: String(message).slice(0, 300),
  });
}

// ── Token usage line for the log ─────────────────────────────────────────────

function usageLine(u) {
  const total = (u.input || 0) + (u.output || 0) + (u.cache_read || 0) + (u.cache_write || 0);
  if (!total) return null;
  const cachePct = Math.round((100 * (u.cache_read || 0)) / total);
  let s = `Токены: ${total.toLocaleString("ru-RU")} (кэш ${cachePct}%)`;
  if (u.cost_usd != null) s += ` · ~$${u.cost_usd.toFixed(3)}`;
  return s;
}

// ── WebSocket lifecycle ──────────────────────────────────────────────────────

function cleanup() {
  if (ws) { ws.onclose = null; ws.close(); ws = null; }
}

function startTask(task) {
  if (running) return;
  cleanup();
  setRunning(true);
  pushEntry({ text: `Запуск: ${task}`, action: "thinking" });

  ws = new WebSocket(WS_URL);

  ws.onopen = () => {
    // session_id ties this task to the dialog history on the server.
    ws.send(JSON.stringify({ task, session_id: sessionId }));
  };

  ws.onmessage = (event) => {
    let msg;
    try { msg = JSON.parse(event.data); } catch { return; }
    const { action = "", details = "" } = msg;

    if (action === "ping") return; // keepalive: receiving it resets SW idle timer

    if (action === "confirm_request" || action === "ask_user") {
      pushEntry({ text: details, action, prompt: true });
      notify(
        action === "confirm_request" ? "WebScout: нужно подтверждение" : "WebScout: агент спрашивает",
        details
      );
      return;
    }

    pushEntry({ text: details, action });

    if (action === "finish") {
      if (msg.usage) {
        const line = usageLine(msg.usage);
        if (line) pushEntry({ text: line, action: "usage" });
      }
      setRunning(false);
      notify("WebScout: задача завершена", details);
    }
  };

  ws.onerror = () => {
    pushEntry({ text: "Ошибка соединения с агентом", action: "", isError: true });
    setRunning(false);
  };

  ws.onclose = () => {
    if (running) {
      pushEntry({ text: "Соединение с агентом закрыто", action: "", isError: true });
      setRunning(false);
      notify("WebScout: соединение потеряно", "Задача прервана");
    }
  };
}

// ── Popup port ───────────────────────────────────────────────────────────────

chrome.runtime.onConnect.addListener((port) => {
  if (port.name !== "popup") return;
  popupPort = port;
  port.onDisconnect.addListener(() => {
    if (popupPort === port) popupPort = null;
  });
  port.onMessage.addListener(async (msg) => {
    await loadState();
    switch (msg.cmd) {
      case "getState":
        port.postMessage({ type: "init", logHistory, running });
        break;
      case "run":
        startTask(msg.task);
        break;
      case "answer":
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ answer: msg.text }));
          pushEntry({ text: `Ответ: ${msg.text}`, action: "thinking" });
        }
        break;
      case "cancel":
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ action: "cancel" }));
        }
        break;
      case "clear":
        // New dialog: wipe the log AND the agent's server-side memory.
        logHistory = [];
        sessionId = crypto.randomUUID();
        chrome.storage.session.set({ logHistory, sessionId });
        break;
    }
  });
});
