const API = "http://localhost:8001";
const WS  = "ws://localhost:8001/ws/status";

const ACTION_ICONS = {
  read_page : "🔍",
  click     : "🖱️",
  type_text : "⌨️",
  navigate  : "🧭",
  thinking  : "💭",
  finish    : "✅",
};

const statusDot   = document.getElementById("status-dot");
const statusLabel = document.getElementById("status-label");
const taskInput   = document.getElementById("task-input");
const runBtn      = document.getElementById("run-btn");
const clearBtn    = document.getElementById("clear-btn");
const log         = document.getElementById("log");

let ws = null;

// ── Helpers ──────────────────────────────────────────────────────────────────

function setStatus(ok) {
  statusDot.className = `dot ${ok ? "dot-ok" : "dot-error"}`;
  statusLabel.textContent = ok ? "Сервер доступен" : "Сервер недоступен";
}

function appendLog(text, action = "", isError = false) {
  const line = document.createElement("div");
  line.className = `log-line${action ? ` action-${action}` : ""}${isError ? " action-error" : ""}`;

  const icon = document.createElement("span");
  icon.className = "icon";
  icon.textContent = isError ? "❌" : (ACTION_ICONS[action] ?? "▸");

  const span = document.createElement("span");
  span.className = "text";
  span.textContent = text;

  line.appendChild(icon);
  line.appendChild(span);
  log.appendChild(line);
  log.scrollTop = log.scrollHeight;
}

function setRunning(running) {
  runBtn.disabled = running;
  taskInput.disabled = running;
}

// ── Health check ─────────────────────────────────────────────────────────────

async function checkHealth() {
  try {
    const res = await fetch(`${API}/health`, { signal: AbortSignal.timeout(3000) });
    setStatus(res.ok);
  } catch {
    // fallback: try root
    try {
      await fetch(`${API}/`, { signal: AbortSignal.timeout(3000) });
      setStatus(true);
    } catch {
      setStatus(false);
    }
  }
}

// ── WebSocket ─────────────────────────────────────────────────────────────────

function openWebSocket(isRetry = false) {
  if (ws) { ws.close(); ws = null; }

  try {
    ws = new WebSocket(WS);
  } catch (e) {
    appendLog("Не удаётся подключиться к серверу агента на localhost:8001, проверь что он запущен", "", true);
    setRunning(false);
    return;
  }

  ws.onmessage = (event) => {
    let msg;
    try { msg = JSON.parse(event.data); } catch { return; }

    const { action = "", details = "" } = msg;
    appendLog(details, action);

    if (action === "finish") {
      setRunning(false);
      ws.close();
      ws = null;
    }
  };

  ws.onerror = () => {
    if (!isRetry) {
      appendLog("Соединение с WebSocket прервалось, пробую переподключиться...");
      setTimeout(() => openWebSocket(true), 1000);
    } else {
      appendLog("Не удаётся подключиться к серверу агента на localhost:8001, проверь что он запущен", "", true);
      setRunning(false);
    }
  };

  ws.onclose = (evt) => {
    // Normal close (code 1000/1001) or already finished — ignore
    if (evt.wasClean || !runBtn.disabled) return;
    if (!isRetry) {
      appendLog("Соединение разорвано, пробую переподключиться...");
      setTimeout(() => openWebSocket(true), 1000);
    } else {
      appendLog("Не удаётся подключиться к серверу агента на localhost:8001, проверь что он запущен", "", true);
      setRunning(false);
    }
  };
}

// ── Run button ────────────────────────────────────────────────────────────────

runBtn.addEventListener("click", async () => {
  const task = taskInput.value.trim();
  if (!task) {
    appendLog("Введи описание задачи перед запуском", "", true);
    return;
  }

  setRunning(true);
  appendLog(`Запуск задачи: ${task}`, "thinking");

  let startOk = false;
  try {
    const res = await fetch(`${API}/task`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task }),
      signal: AbortSignal.timeout(10000),
    });

    if (!res.ok) {
      const body = await res.text().catch(() => "");
      appendLog(`Сервер вернул ошибку ${res.status}: ${body}`, "", true);
      setRunning(false);
      return;
    }
    startOk = true;
  } catch (e) {
    appendLog("Не удаётся подключиться к серверу агента на localhost:8001, проверь что он запущен", "", true);
    setRunning(false);
    return;
  }

  if (startOk) {
    appendLog("Агент запущен, ожидаю обновления...", "thinking");
    openWebSocket();
  }
});

// ── Clear button ──────────────────────────────────────────────────────────────

clearBtn.addEventListener("click", () => {
  log.innerHTML = "";
});

// ── Init ──────────────────────────────────────────────────────────────────────

checkHealth();
