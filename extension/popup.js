// Popup: pure view over the background service worker (background.js), which
// owns the WebSocket. Tasks keep running when this popup is closed; reopening
// restores the log from chrome.storage.session (wiped on browser close).

const API = "http://localhost:8001";

const ACTION_ICONS = {
  read_page       : "🔍",
  click           : "🖱️",
  type_text       : "⌨️",
  navigate        : "🧭",
  thinking        : "💭",
  finish          : "✅",
  confirm_request : "⚠️",
  ask_user        : "❓",
  usage           : "📊",
};

const statusDot   = document.getElementById("status-dot");
const statusLabel = document.getElementById("status-label");
const taskInput   = document.getElementById("task-input");
const runBtn      = document.getElementById("run-btn");
const clearBtn    = document.getElementById("clear-btn");
const log         = document.getElementById("log");

let port = null;
let running = false;

const isExtension =
  typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.connect;

// ── Rendering ────────────────────────────────────────────────────────────────

function setStatus(ok) {
  statusDot.className = `dot ${ok ? "dot-ok" : "dot-error"}`;
  statusLabel.textContent = ok ? "Сервер доступен" : "Сервер недоступен";
}

function setRunning(val) {
  running = val;
  taskInput.disabled = val;
  runBtn.disabled = false; // while running the button becomes "Stop"
  runBtn.textContent = val ? "⛔ Остановить" : "Запустить агента";
  runBtn.classList.toggle("btn-stop", val);
}

function renderLine({ text, action = "", isError = false }) {
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

// Interactive human-in-the-loop block. The answer goes to the service worker,
// which forwards it over its WebSocket — so it works even after the popup
// was closed and reopened while the agent is waiting.
function renderPrompt({ text, action }) {
  const box = document.createElement("div");
  box.className = "prompt-box";

  const question = document.createElement("div");
  question.className = "prompt-question";
  question.textContent = `${ACTION_ICONS[action]} ${text}`;
  box.appendChild(question);

  const controls = document.createElement("div");
  controls.className = "prompt-controls";

  function sendAnswer(answer) {
    if (!port) return;
    port.postMessage({ cmd: "answer", text: answer });
    box.classList.add("prompt-answered");
    controls.querySelectorAll("button, input").forEach((el) => (el.disabled = true));
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

function renderEntry(entry, { live = false } = {}) {
  if (entry.prompt && live) {
    renderPrompt(entry);
  } else {
    renderLine(entry);
  }
}

// ── Service worker connection ────────────────────────────────────────────────

function connectBackground() {
  port = chrome.runtime.connect({ name: "popup" });

  port.onMessage.addListener((msg) => {
    if (msg.type === "init") {
      log.innerHTML = "";
      const entries = msg.logHistory || [];
      entries.forEach((entry, i) => {
        // An unanswered question at the tail is still live — the SW holds the
        // WS open; render it interactively so the user can answer it now.
        const isLiveTail = msg.running && entry.prompt && i === entries.length - 1;
        renderEntry(entry, { live: isLiveTail });
      });
      setRunning(msg.running);
    } else if (msg.type === "log") {
      renderEntry(msg.entry, { live: running });
    } else if (msg.type === "state") {
      setRunning(msg.running);
    }
  });

  port.postMessage({ cmd: "getState" });
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

// ── Buttons ──────────────────────────────────────────────────────────────────

runBtn.addEventListener("click", () => {
  if (!port) return;
  if (running) {
    port.postMessage({ cmd: "cancel" });
    return;
  }
  const task = taskInput.value.trim();
  if (!task) {
    renderLine({ text: "Введи описание задачи перед запуском", isError: true });
    return;
  }
  port.postMessage({ cmd: "run", task });
  taskInput.value = "";
});

// Ctrl+Enter / Cmd+Enter in the textarea launches the agent
taskInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && !running) {
    e.preventDefault();
    runBtn.click();
  }
});

clearBtn.addEventListener("click", () => {
  log.innerHTML = "";
  if (port) port.postMessage({ cmd: "clear" });
});

// ── Init ─────────────────────────────────────────────────────────────────────

if (isExtension) {
  connectBackground();
} else {
  renderLine({
    text: "Страница открыта вне расширения Chrome — установи её через chrome://extensions (Load unpacked).",
    isError: true,
  });
}
checkHealth();
