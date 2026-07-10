"""
Adapter layer: FastAPI HTTP + WebSocket wrapper over AgentSession.
No queues — task submission and status streaming share one WebSocket.
"""

from __future__ import annotations

import asyncio
import html
import os
import secrets
from datetime import datetime, timezone

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from agent.loop import AgentSession

# Shared secret for API authentication (set in .env or docker-compose)
API_SECRET = os.environ.get("API_SECRET", "")

# Dialog histories per extension session. Survive WS reconnects (the popup
# closes its socket every time it's dismissed); reset when the browser is
# restarted — the extension then sends a fresh session_id.
_HISTORIES: dict[str, list] = {}
_MAX_SESSIONS = 8

app = FastAPI(title="WebScout Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8001", "http://localhost:3000"],
    allow_origin_regex=r"chrome-extension://.*",
    allow_methods=["GET"],
    allow_headers=["*"],
)


MAX_TASK_LEN = 4000


def _sanitize_task(task: str) -> str:
    """
    Basic input hygiene: unescape HTML entities, drop control characters,
    cap the length. This is NOT a prompt-injection defence — the real
    injection surface is text on the web pages the agent reads, and the
    mitigation for that is confirm_action before any impactful action.
    """
    task = html.unescape(task)
    task = "".join(ch for ch in task if ch == "\n" or ch == "\t" or ord(ch) >= 32)
    return task.strip()[:MAX_TASK_LEN]


def _verify_auth(authorization: str | None) -> None:
    """Verify Bearer token if API_SECRET is set."""
    if not API_SECRET:
        return  # No auth configured
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(token, API_SECRET):
        raise HTTPException(status_code=401, detail="Invalid API key")


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health(authorization: str | None = Header(default=None)) -> dict:
    _verify_auth(authorization)
    return {"status": "ok"}


@app.websocket("/ws")
async def ws_handler(websocket: WebSocket) -> None:
    # Verify auth via query param for WebSocket (headers not always available)
    token = websocket.query_params.get("token", "")
    if API_SECRET and not secrets.compare_digest(token, API_SECRET):
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await websocket.accept()

    async def send_status(msg: dict) -> None:
        msg["timestamp"] = datetime.now(timezone.utc).isoformat()
        await websocket.send_json(msg)

    async def keepalive() -> None:
        # MV3 service workers idle out after ~30s of silence; periodic pings
        # keep the extension's background connection alive during long steps.
        try:
            while True:
                await asyncio.sleep(15)
                await websocket.send_json({"action": "ping"})
        except Exception:  # noqa: BLE001 — socket closed, nothing to keep alive
            return

    ping_task = asyncio.create_task(keepalive())
    pending: dict | None = None  # a "task" message swallowed by the reader
    try:
        while True:
            data = pending or await websocket.receive_json()
            pending = None
            if "task" not in data:
                continue
            task = _sanitize_task(str(data.get("task", "")))
            if not task:
                await websocket.send_json({"action": "error", "details": "Empty task"})
                continue
            session_id = str(data.get("session_id") or "default")

            answers: asyncio.Queue[str] = asyncio.Queue()
            user_cancelled = False
            disconnected = False

            async def wait_user_answer(msg: dict) -> str:
                """Human in the loop: send the question, block until an answer arrives."""
                await send_status(msg)
                return await answers.get()

            session = AgentSession(
                task=task,
                status_callback=send_status,
                input_callback=wait_user_answer,
                history=_HISTORIES.get(session_id),
            )
            run_task = asyncio.create_task(session.run())

            async def read_until_done() -> None:
                """Feed answers to the loop; handle cancel and disconnect."""
                nonlocal user_cancelled, disconnected, pending
                try:
                    while not run_task.done():
                        reply = await websocket.receive_json()
                        if reply.get("action") == "cancel":
                            user_cancelled = True
                            run_task.cancel()
                            return
                        if "task" in reply:  # next task raced the run's end
                            pending = reply
                            return
                        answer = _sanitize_task(str(reply.get("answer", "")))
                        if answer:
                            await answers.put(answer)
                except WebSocketDisconnect:
                    disconnected = True
                    run_task.cancel()

            reader = asyncio.create_task(read_until_done())
            try:
                await run_task
            except asyncio.CancelledError:
                if user_cancelled:
                    await send_status({
                        "step": 0, "action": "finish",
                        "details": "⛔ Задача отменена пользователем.",
                        "usage": session.usage_summary(),
                    })
                elif not disconnected:
                    raise  # our own task is being cancelled (server shutdown)
            except Exception as exc:  # noqa: BLE001
                if not disconnected:
                    await send_status({
                        "step": 0, "action": "finish",
                        "details": f"Ошибка агента: {exc}",
                        "usage": session.usage_summary(),
                    })
            finally:
                reader.cancel()
                # Save even a partial run — the dialog context survives the
                # popup being closed mid-task. LRU-cap the session store.
                _HISTORIES.pop(session_id, None)
                _HISTORIES[session_id] = session.messages
                while len(_HISTORIES) > _MAX_SESSIONS:
                    _HISTORIES.pop(next(iter(_HISTORIES)))
            if disconnected:
                return
    except WebSocketDisconnect:
        pass
    finally:
        ping_task.cancel()
