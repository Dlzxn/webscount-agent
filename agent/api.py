"""
Adapter layer: FastAPI HTTP + WebSocket wrapper over AgentSession.
No browser logic here — just routing and queue wiring.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agent.loop import AgentSession

app = FastAPI(title="WebScout Agent API")

app.add_middleware(
    CORSMiddleware,
    # Explicit origins for localhost dev + Chrome extension popup.
    allow_origins=["http://localhost:8001", "http://localhost:3000", "null"],
    # chrome-extension://<id> origins are covered by the regex below.
    allow_origin_regex=r"chrome-extension://.*",
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# One global queue per running task.
# A new POST /task replaces the queue, so stale WS connections drain and close.
_status_queue: asyncio.Queue[dict | None] = asyncio.Queue()


class TaskRequest(BaseModel):
    task: str


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/task")
async def start_task(body: TaskRequest) -> dict:
    global _status_queue
    _status_queue = asyncio.Queue()

    async def status_callback(msg: dict) -> None:
        msg["timestamp"] = datetime.now(timezone.utc).isoformat()
        await _status_queue.put(msg)

    asyncio.create_task(_run_agent(body.task, status_callback))
    return {"status": "started"}


@app.websocket("/ws/status")
async def ws_status(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            msg = await _status_queue.get()
            if msg is None:
                # Sentinel: agent finished, close the connection.
                break
            await websocket.send_json(msg)
    except WebSocketDisconnect:
        pass


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _run_agent(task: str, callback: object) -> None:
    try:
        session = AgentSession(task=task, status_callback=callback)  # type: ignore[arg-type]
        await session.run()
    except Exception as exc:  # noqa: BLE001
        ts = datetime.now(timezone.utc).isoformat()
        await _status_queue.put(
            {
                "step": 0,
                "action": "finish",
                "details": f"Ошибка агента: {exc}",
                "timestamp": ts,
            }
        )
    finally:
        await _status_queue.put(None)  # Close WS listener.
