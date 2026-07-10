"""
Adapter layer: FastAPI HTTP + WebSocket wrapper over AgentSession.
No queues — task submission and status streaming share one WebSocket.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from agent.loop import AgentSession

app = FastAPI(title="WebScout Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8001", "http://localhost:3000", "null"],
    allow_origin_regex=r"chrome-extension://.*",
    allow_methods=["GET"],
    allow_headers=["*"],
)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.websocket("/ws")
async def ws_handler(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            if "task" not in data:
                # Stray message (e.g. an "answer" after the session ended) — ignore.
                continue
            task = str(data.get("task", "")).strip()
            if not task:
                await websocket.send_json({"action": "error", "details": "Empty task"})
                continue

            async def send_status(msg: dict) -> None:
                msg["timestamp"] = datetime.now(timezone.utc).isoformat()
                await websocket.send_json(msg)

            async def wait_user_answer(msg: dict) -> str:
                """Human in the loop: send the question, block until an answer arrives."""
                await send_status(msg)
                while True:
                    reply = await websocket.receive_json()
                    answer = str(reply.get("answer", "")).strip()
                    if answer:
                        return answer

            session = AgentSession(
                task=task,
                status_callback=send_status,
                input_callback=wait_user_answer,
            )
            try:
                await session.run()
            except WebSocketDisconnect:
                raise
            except Exception as exc:  # noqa: BLE001
                await send_status(
                    {"step": 0, "action": "finish", "details": f"Ошибка агента: {exc}"}
                )
    except WebSocketDisconnect:
        pass
