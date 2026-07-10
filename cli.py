"""
Терминальный клиент WebScout Agent.

Задача вводится в терминале, шаги агента (вызовы инструментов с аргументами)
стримятся сюда же в реальном времени — параллельно с действиями в браузере.
Human-in-the-loop (подтверждения, вопросы агента) тоже работает через терминал.

Использование:
    uv run python cli.py                 # интерактивный диалог
    uv run python cli.py "задача..."     # одна задача и выход

Ctrl+C прерывает работу: разрыв соединения отменяет задачу на сервере.
Контекст диалога сохраняется между задачами одной CLI-сессии.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid

import websockets

WS_URL = os.environ.get("AGENT_WS_URL", "ws://localhost:8001/ws")

ICONS = {
    "read_page": "🔍",
    "click": "🖱️ ",
    "type_text": "⌨️ ",
    "navigate": "🧭",
    "thinking": "💭",
    "finish": "✅",
    "subagent": "🤖",
    "screenshot": "📸",
    "confirm_request": "⚠️ ",
    "ask_user": "❓",
    "error": "❌",
}

_COLORS = {"finish": "32", "thinking": "2", "navigate": "36", "subagent": "35", "error": "31"}


def c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m"


async def ainput(prompt: str) -> str:
    return (await asyncio.to_thread(input, prompt)).strip()


def _print_usage(usage: dict) -> None:
    total = sum(usage.get(k) or 0 for k in ("input", "output", "cache_read", "cache_write"))
    if not total:
        return
    line = f"     📊 Токены: {total:,}".replace(",", " ")
    cache = usage.get("cache_read") or 0
    line += f" (кэш {round(100 * cache / total)}%)"
    if usage.get("cost_usd") is not None:
        line += f" · ~${usage['cost_usd']:.3f}"
    print(c(line, "2"))


async def run_task(ws, task: str, session_id: str) -> None:
    """Отправляет задачу и стримит шаги до finish."""
    await ws.send(json.dumps({"task": task, "session_id": session_id}))
    while True:
        try:
            msg = json.loads(await ws.recv())
        except websockets.ConnectionClosed:
            print(c("Соединение с агентом закрыто.", "31"))
            raise SystemExit(1)

        action = msg.get("action", "")
        details = msg.get("details", "")
        if action == "ping":
            continue

        # Human in the loop: агент ждёт ответа человека
        if action in ("confirm_request", "ask_user"):
            print(f"\n{ICONS[action]} {c(details, '33')}")
            if action == "confirm_request":
                ans = await ainput(c("   Подтвердить? [y/N]: ", "33"))
                answer = (
                    "Да, подтверждаю, выполняй."
                    if ans.lower() in ("y", "yes", "д", "да")
                    else "Нет, не выполняй это действие."
                )
            else:
                answer = ""
                while not answer:
                    answer = await ainput(c("   Твой ответ: ", "33"))
            await ws.send(json.dumps({"answer": answer}))
            continue

        step = msg.get("step")
        prefix = f"[{step:>2}] " if isinstance(step, int) and step > 0 else "     "
        icon = ICONS.get(action, "▸")
        print(f"{prefix}{icon} {c(details, _COLORS.get(action, '0'))}")

        if action == "finish":
            if isinstance(msg.get("usage"), dict):
                _print_usage(msg["usage"])
            return


async def main() -> None:
    os.system("")  # включает обработку ANSI-кодов в консоли Windows
    session_id = str(uuid.uuid4())
    once = " ".join(sys.argv[1:]).strip()

    print(c("WebScout Agent — терминальный клиент", "1;35") + c(f"  {WS_URL}", "2"))
    try:
        async with websockets.connect(WS_URL, max_size=None) as ws:
            if once:
                await run_task(ws, once, session_id)
                return
            print(c("Введи задачу (пустая строка — выход). Контекст диалога сохраняется между задачами.", "2"))
            while True:
                task = await ainput(c("\nзадача> ", "1;35"))
                if not task:
                    return
                await run_task(ws, task, session_id)
    except (ConnectionRefusedError, OSError):
        print(c("Не удалось подключиться к агенту. Он запущен? (uv run python main.py)", "31"))
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # Разрыв WebSocket отменяет выполняющуюся задачу на сервере.
        print(c("\n⛔ Прервано. Задача на сервере отменена.", "31"))
