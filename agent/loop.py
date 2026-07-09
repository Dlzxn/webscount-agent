"""
Orchestration layer: agent loop that ties MCP client and LLM client together.
No knowledge of WebSocket or HTTP — communicates externally only through status_callback.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from agent.llm_client import AgentLLM, extract_text, extract_tool_use
from agent.local_tools import (
    ASK_USER_TOOL_SCHEMA,
    CONFIRM_ACTION_TOOL_SCHEMA,
    FINISH_TOOL_SCHEMA,
)
from agent.mcp_client import MCPToolClient

logger = logging.getLogger("agent.loop")

MAX_ITERATIONS = 30
COMPRESS_THRESHOLD = 20
TAIL_KEEP = 10

StatusCallback = Callable[[dict], Awaitable[None]]
# Sends a question dict to the user and waits for their text answer.
InputCallback = Callable[[dict], Awaitable[str]]

# Maps MCP tool names to the action strings expected by the extension.
_ACTION_MAP: dict[str, str] = {
    "navigate": "navigate",
    "go_back": "navigate",
    "scroll": "read_page",
    "read_page": "read_page",
    "get_full_text": "read_page",
    "get_current_state": "read_page",
    "click": "click",
    "select_option": "click",
    "press_key": "click",
    "handle_dialog": "click",
    "type_text": "type_text",
}


def _tool_action(name: str) -> str:
    return _ACTION_MAP.get(name, name)


def _tool_details(name: str, args: dict) -> str:
    match name:
        case "navigate":
            return args.get("url", "")
        case "go_back":
            return "Возврат на предыдущую страницу"
        case "scroll":
            return f"Прокрутка {args.get('direction', '')} ({args.get('amount', '')})"
        case "read_page":
            return "Читаю страницу..."
        case "get_full_text":
            return "Читаю полный текст страницы..."
        case "get_current_state":
            return "Проверяю текущий URL и заголовок"
        case "click":
            return f"Клик на элемент #{args.get('element_id', '?')}"
        case "select_option":
            return f"Выбираю: {args.get('option_label', '')} в элементе #{args.get('element_id', '?')}"
        case "press_key":
            return f"Клавиша: {args.get('key', '')}"
        case "handle_dialog":
            return f"Диалог: {args.get('action', '')}"
        case "type_text":
            text = str(args.get("text", ""))[:60]
            submit = args.get("submit", False)
            suffix = " + Enter" if submit else ""
            return f'Ввод: "{text}"{suffix} в элемент #{args.get("element_id", "?")}'
        case _:
            return str(args)


def _compress_messages(messages: list[dict]) -> list[dict]:
    """
    Keep messages[0] (original task) + last TAIL_KEEP messages,
    ensuring the tail starts with an assistant turn (correct alternation).
    """
    tail = messages[-TAIL_KEEP:]
    # messages[0] is always role=user, so tail must begin with assistant.
    first_assistant = next(
        (i for i, m in enumerate(tail) if m["role"] == "assistant"), None
    )
    if first_assistant is None:
        return messages  # Can't compress safely — keep everything.
    return [messages[0]] + tail[first_assistant:]


class AgentSession:
    """
    Single-use agent session for one user task.

    status_callback is called on every significant step:
        {"step": int, "action": str, "details": str}
    The caller (api.py) adds "timestamp" and routes the dict to the WebSocket.

    input_callback sends the same kind of dict (action "confirm_request" or
    "ask_user") and blocks until the human answers; the answer text is fed
    back to the LLM as the tool result.
    """

    def __init__(
        self,
        task: str,
        status_callback: StatusCallback,
        input_callback: InputCallback,
    ) -> None:
        self._task = task
        self._callback = status_callback
        self._input = input_callback
        self._llm = AgentLLM()

    async def run(self) -> dict[str, Any]:
        logger.info("AgentSession.run() started for task: %s", self._task[:80])
        async with MCPToolClient() as mcp:
            logger.info("MCPToolClient connected, listing tools")
            mcp_tools = await mcp.list_tools()
            logger.info("Got %d MCP tools", len(mcp_tools))
            all_tools = mcp_tools + [
                FINISH_TOOL_SCHEMA,
                ASK_USER_TOOL_SCHEMA,
                CONFIRM_ACTION_TOOL_SCHEMA,
            ]

            messages: list[dict] = [{"role": "user", "content": self._task}]
            step = 0

            for _ in range(MAX_ITERATIONS):
                step += 1

                # ── Thinking ─────────────────────────────────────────────────
                await self._callback(
                    {"step": step, "action": "thinking", "details": "Анализирую..."}
                )

                response = await self._llm.get_next_action(messages, all_tools)

                reasoning = extract_text(response)
                if reasoning:
                    await self._callback(
                        {
                            "step": step,
                            "action": "thinking",
                            "details": reasoning[:300],
                        }
                    )

                tool_use = extract_tool_use(response)

                # ── No tool call → LLM answered in plain text ────────────────
                if tool_use is None:
                    summary = reasoning or "Задача завершена."
                    await self._callback(
                        {"step": step, "action": "finish", "details": summary}
                    )
                    return {"status": "completed", "result": summary}

                # ── Local tool: finish ────────────────────────────────────────
                if tool_use.name == "finish":
                    result: str = tool_use.input.get("result", "")
                    success: bool = tool_use.input.get("success", True)
                    await self._callback(
                        {"step": step, "action": "finish", "details": result}
                    )
                    return {"status": "completed", "result": result, "success": success}

                # ── Local tools: ask_user / confirm_action (human in the loop) ─
                # Both pause the loop, wait for the human's answer over the
                # WebSocket and feed it back to the LLM as the tool result.
                if tool_use.name in ("ask_user", "confirm_action"):
                    if tool_use.name == "confirm_action":
                        prompt_action = "confirm_request"
                        prompt_text = tool_use.input.get("action_description", "")
                    else:
                        prompt_action = "ask_user"
                        prompt_text = tool_use.input.get("question", "")

                    answer = await self._input(
                        {"step": step, "action": prompt_action, "details": prompt_text}
                    )

                    messages.append({"role": "assistant", "content": response.content})
                    messages.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": tool_use.id,
                                    "content": f"Ответ пользователя: {answer}",
                                }
                            ],
                        }
                    )
                    if len(messages) > COMPRESS_THRESHOLD:
                        messages = _compress_messages(messages)
                    continue

                # ── MCP tool call ─────────────────────────────────────────────
                action = _tool_action(tool_use.name)
                details = _tool_details(tool_use.name, tool_use.input)
                await self._callback({"step": step, "action": action, "details": details})

                tool_result = await mcp.call_tool(tool_use.name, dict(tool_use.input))

                # Append the full exchange to message history.
                messages.append({"role": "assistant", "content": response.content})
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_use.id,
                                "content": tool_result,
                            }
                        ],
                    }
                )

                # ── Context compression ───────────────────────────────────────
                if len(messages) > COMPRESS_THRESHOLD:
                    messages = _compress_messages(messages)

            # ── Max iterations reached ────────────────────────────────────────
            await self._callback(
                {
                    "step": step,
                    "action": "finish",
                    "details": f"Достигнут лимит итераций ({MAX_ITERATIONS}). Задача не завершена.",
                }
            )
            return {"status": "max_iterations_reached"}
