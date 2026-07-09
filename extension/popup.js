const API = "http://localhost:8001";
const WS  = "ws://localhost:8001/ws";

const ACTION_ICONS = {
  read_page       : "🔍",
  click           : "🖱️",
  type_text       : "⌨️",
  navigate        : "🧭",
  thinking        : "💭",
  finish          : "✅",
  confirm_request : "⚠️",
  ask_user        : "❓",
};

const statusDot   = document.getElementById("status-dot");
const statusLabel = document.getElementById("status-label");
const taskInput   = document.getElementById("task-input");
const runBtn      = document.getElementById("run-btn");
const clearBtn    = document.getElementById("clear-btn");
const log         = document.getElementById("log");

let ws = null;
let running = false;

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

// Interactive human-in-the-loop block: the agent is paused until we send
// {"answer": "..."} back over the same WebSocket.
function appendPrompt(details, action) {
  const box = document.createElement("div");
  box.className = "prompt-box";

  const question = document.createElement("div");
  question.className = "prompt-question";
  question.textContent = `${ACTION_ICONS[action]} ${details}`;
  box.appendChild(question);

  const controls = document.createElement("div");
  controls.className = "prompt-controls";

  function sendAnswer(answer) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({ answer }));
    box.classList.add("prompt-answered");
    controls.querySelectorAll("button, input").forEach((el) => (el.disabled = true));
    appendLog(`Ответ: ${answer}`, "thinking");
  }

  if (action === "confirm_request") {
    const yesBtn = document.createElement("button");
    yesBtn.className = "btn btn-yes";
    yesBtn.textContent = "✅ Да, делаем";
    yesBtn.addEventListener("click", () => sendAnswer("Да, подтверждаю, выполняй."));

    const noBtn = document.createElement("button");
    noBtn.className = "btn btn-no";
    noBtn.textContent = "❌ Нет";
    noBtn.addEventListener("click", () => sendAnswer("Нет, не выполняй это действие."));

    controls.appendChild(yesBtn);
    controls.appendChild(noBtn);
  } else {
    const input = document.createElement("input");
    input.type = "text";
    input.className = "prompt-input";
    input.placeholder = "Твой ответ агенту...";

    const sendBtn = document.createElement("button");
    sendBtn.className = "btn btn-yes";
    sendBtn.textContent = "Отправить";

    const submit = () => {
      const val = input.value.trim();
      if (val) sendAnswer(val);
    };
    sendBtn.addEventListener("click", submit);
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") submit();
    });

    controls.appendChild(input);
    controls.appendChild(sendBtn);
    setTimeout(() => input.focus(), 0);
  }

  box.appendChild(controls);
  log.appendChild(box);
  log.scrollTop = log.scrollHeight;
}

function setRunning(val) {
  running = val;
  runBtn.disabled = val;
  taskInput.disabled = val;
}

function cleanup() {
  if (ws) { ws.onclose = null; ws.close(); ws = null; }
}

// ── Health check ─────────────────────────────────────────────────────────────

async function checkHealth() {
  try {
    const res = await fetch(`${API}/health`, { signal: AbortSignal.timeout(3000) });
    setStatus(res.ok);
  } catch {
    setStatus(false);
  }
}

// ── Run button — single WS for task + status ─────────────────────────────────

runBtn.addEventListener("click", () => {
  const task = taskInput.value.trim();
  if (!task) {
    appendLog("Введи описание задачи перед запуском", "", true);
    return;
  }

  cleanup();
  setRunning(true);
  appendLog(`Запуск: ${task}`, "thinking");

  ws = new WebSocket(WS);

  ws.onopen = () => {
    ws.send(JSON.stringify({ task }));
  };

  ws.onmessage = (event) => {
    let msg;
    try { msg = JSON.parse(event.data); } catch { return; }

    const { action = "", details = "" } = msg;

    if (action === "confirm_request" || action === "ask_user") {
      appendPrompt(details, action);
      return;
    }

    appendLog(details, action);

    if (action === "finish") {
      setRunning(false);
    }
  };

  ws.onerror = () => {
    appendLog("Ошибка соединения с агентом", "", true);
    setRunning(false);
  };

  ws.onclose = () => {
    if (running) {
      appendLog("Соединение закрыто", "", true);
      setRunning(false);
    }
  };
});

// ── Clear button ──────────────────────────────────────────────────────────────

clearBtn.addEventListener("click", () => {
  log.innerHTML = "";
});

// ── Init ──────────────────────────────────────────────────────────────────────

checkHealth();
