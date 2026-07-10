"""
Orchestration layer: agent loop that ties MCP client and LLM client together.
No knowledge of WebSocket or HTTP — communicates externally only through status_callback.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from agent.llm_client import AgentLLM, extract_text, extract_tool_use, extract_all_tool_uses
from agent.local_tools import (
    ASK_USER_TOOL_SCHEMA,
    CONFIRM_ACTION_TOOL_SCHEMA,
    EXTRACT_DATA_TOOL_SCHEMA,
    FINISH_TOOL_SCHEMA,
)
from agent.mcp_client import MCPToolClient
from agent.subagent import ExtractionSubAgent

logger = logging.getLogger("agent.loop")

MAX_ITERATIONS = 30
# Compression rewrites the history prefix and thus invalidates the message
# cache — keep the threshold high enough that it fires rarely, not every turn.
COMPRESS_THRESHOLD = 30
TAIL_KEEP = 10
TOOL_RESULT_MAX_LEN = 5000  # truncate long tool results before adding to history

# Old page snapshots carry no information the latest one doesn't — stub them
# out during compression. Short results (user answers, errors) stay intact.
STUB_MIN_LEN = 400
KEEP_FULL_RESULTS = 2  # newest tool-result messages that keep full content
RESULT_STUB = (
    "[Устаревший вывод инструмента скрыт для экономии контекста. "
    "Актуальное состояние страницы — в последнем snapshot; "
    "при необходимости вызови read_page или get_full_text заново.]"
)

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
    "list_tabs": "read_page",
    "switch_tab": "navigate",
    "screenshot": "screenshot",
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
        case "list_tabs":
            return "Список открытых вкладок"
        case "switch_tab":
            return f"Переключение на вкладку #{args.get('index', '?')}"
        case "screenshot":
            return "Смотрю на экран (скриншот)..."
        case "type_text":
            text = str(args.get("text", ""))[:60]
            submit = args.get("submit", False)
            suffix = " + Enter" if submit else ""
            return f'Ввод: "{text}"{suffix} в элемент #{args.get("element_id", "?")}'
        case _:
            return str(args)


def _stub_old_tool_results(messages: list[dict]) -> list[dict]:
    """
    Replace bulky tool results (page snapshots, full texts) with a short stub
    in all but the KEEP_FULL_RESULTS newest tool-result messages. Originals
    are not mutated. Idempotent: already-stubbed results are under STUB_MIN_LEN.
    """
    result_idxs = [
        i
        for i, m in enumerate(messages)
        if m["role"] == "user" and isinstance(m["content"], list)
    ]
    keep = set(result_idxs[-KEEP_FULL_RESULTS:])

    out: list[dict] = []
    for i, msg in enumerate(messages):
        if i not in result_idxs or i in keep:
            out.append(msg)
            continue
        blocks = [
            {**b, "content": RESULT_STUB}
            if (
                isinstance(b, dict)
                and b.get("type") == "tool_result"
                and (
                    # bulky text (snapshots, full page text)
                    (isinstance(b.get("content"), str) and len(b["content"]) > STUB_MIN_LEN)
                    # block lists = screenshots — the most expensive history items
                    or isinstance(b.get("content"), list)
                )
            )
            else b
            for b in msg["content"]
        ]
        out.append({**msg, "content": blocks})
    return out


class _SelfCorrection:
    """
    Deterministic self-correction: watches MCP tool calls and their results,
    and injects a corrective hint into the observation when the agent is
    stuck — repeating the same call verbatim or hitting errors in a row.
    The hint arrives as part of the tool result, so the model can't miss it.
    """

    ERROR_MARKERS = ("Ошибка", "не найден", "не найдена", "не удалось")

    def __init__(self) -> None:
        self._error_streak = 0
        self._last_call: tuple[str, str] | None = None
        self._repeat_count = 0

    def hint_for(self, name: str, args: dict, result: str | list) -> str | None:
        call = (name, json.dumps(args, sort_keys=True, ensure_ascii=False))
        if call == self._last_call:
            self._repeat_count += 1
        else:
            self._repeat_count = 0
        self._last_call = call

        head = result[:150] if isinstance(result, str) else ""
        is_error = any(m in head for m in self.ERROR_MARKERS)
        self._error_streak = self._error_streak + 1 if is_error else 0

        hints: list[str] = []
        if self._repeat_count >= 1:
            hints.append(
                f"⚠️ SELF-CHECK: ты вызвал {name} с теми же аргументами "
                f"{self._repeat_count + 1} раз(а) подряд — результат не изменится. "
                "Выбери ДРУГОЕ действие или другие аргументы."
            )
        if self._error_streak >= 2:
            hints.append(
                f"⚠️ SELF-CHECK: {self._error_streak} неудачных действия подряд. "
                "Остановись и пересмотри план: вызови read_page для актуального "
                "состояния страницы, попробуй другой элемент или другой путь к цели. "
                "Если совсем застрял — спроси человека через ask_user."
            )
        return "\n\n".join(hints) if hints else None


SUMMARY_PREFIX = "[Сводка ранее выполненных шагов агента]\n"


def _split_summary(head: dict) -> tuple[str, dict]:
    """Extract a previously attached summary block from the first message."""
    content = head["content"]
    if not isinstance(content, list):
        return "", head
    summary = ""
    blocks = []
    for b in content:
        if (
            isinstance(b, dict)
            and b.get("type") == "text"
            and b.get("text", "").startswith(SUMMARY_PREFIX)
        ):
            summary = b["text"][len(SUMMARY_PREFIX):]
        else:
            blocks.append(b)
    return summary, {**head, "content": blocks}


def _attach_summary(head: dict, summary: str) -> dict:
    content = head["content"]
    blocks = (
        [{"type": "text", "text": content}] if isinstance(content, str) else list(content)
    )
    blocks.append({"type": "text", "text": SUMMARY_PREFIX + summary})
    return {**head, "content": blocks}


def _compress_messages(messages: list[dict], summary: str = "") -> list[dict]:
    """
    Keep messages[0] (original task, with the running summary of dropped steps
    attached) + last TAIL_KEEP messages, ensuring the tail starts with an
    assistant turn (correct alternation), and stub bulky tool results older
    than the last KEEP_FULL_RESULTS.
    """
    tail = messages[-TAIL_KEEP:]
    # messages[0] is always role=user, so tail must begin with assistant.
    first_assistant = next(
        (i for i, m in enumerate(tail) if m["role"] == "assistant"), None
    )
    if first_assistant is None:
        return messages  # Can't compress safely — keep everything.
    _, head = _split_summary(messages[0])
    if summary:
        head = _attach_summary(head, summary)
    return [head] + _stub_old_tool_results(tail[first_assistant:])


class AgentSession:
    """
    Agent session for one user task.

    history — message history of previous tasks in the same dialog; the new
    task is appended to it, so the agent sees what was done before. After
    run() (even a failed one) the caller reads back `self.messages` to carry
    the dialog on to the next task.

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
        history: list[dict] | None = None,
    ) -> None:
        self._task = task
        self._callback = status_callback
        self._input = input_callback
        self._llm = AgentLLM()
        self.messages: list[dict] = list(history) if history else []

    def _append_task(self) -> None:
        """
        Add the new task to the dialog history. A previous task usually leaves
        the history ending with a user turn (tool results) — merge the task
        into it as an extra text block to keep strict user/assistant
        alternation. tool_result blocks stay first in the message, as the API
        requires.
        """
        if self.messages and self.messages[-1]["role"] == "user":
            content = self.messages[-1]["content"]
            blocks = (
                [{"type": "text", "text": content}]
                if isinstance(content, str)
                else list(content)
            )
            blocks.append(
                {"type": "text", "text": f"Новая задача пользователя: {self._task}"}
            )
            self.messages[-1] = {"role": "user", "content": blocks}
        else:
            self.messages.append({"role": "user", "content": self._task})

    def usage_summary(self) -> dict:
        """Cumulative token usage + cost estimate for this session's LLM."""
        return self._llm.usage_summary()

    async def _compress(self, messages: list[dict]) -> list[dict]:
        """
        Model-routed compression: the cheap model (settings.anthropic_small_model)
        summarizes the steps being dropped, so facts found mid-task survive
        compression. On any summarizer failure, degrades to plain dropping.
        """
        old_summary, _ = _split_summary(messages[0])
        dropped = messages[1 : max(1, len(messages) - TAIL_KEEP)]
        summary = old_summary
        try:
            summary = await self._llm.summarize_steps(old_summary, dropped)
        except Exception as exc:  # noqa: BLE001
            logger.warning("history summarization failed, dropping steps plainly: %s", exc)
        return _compress_messages(messages, summary)

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
                EXTRACT_DATA_TOOL_SCHEMA,
            ]
            corrector = _SelfCorrection()

            self._append_task()
            messages = self.messages  # alias; re-bound together on compression
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

                tool_uses = extract_all_tool_uses(response)

                # ── No tool call → LLM answered in plain text ────────────────
                if not tool_uses:
                    summary = reasoning or "Задача завершена."
                    await self._callback(
                        {"step": step, "action": "finish", "details": summary,
                         "usage": self.usage_summary()}
                    )
                    # Keep the answer in history for the next task in this dialog.
                    messages.append({"role": "assistant", "content": response.content})
                    return {"status": "completed", "result": summary}

                # ── Process tool calls sequentially ─────────────────────────
                tool_results = []
                for tool_use in tool_uses:
                    # ── Local tool: finish ────────────────────────────────
                    if tool_use.name == "finish":
                        result: str = tool_use.input.get("result", "")
                        success: bool = tool_use.input.get("success", True)
                        await self._callback(
                            {"step": step, "action": "finish", "details": result,
                             "usage": self.usage_summary()}
                        )
                        # Close the exchange in history so the next task in
                        # this dialog continues from a valid state.
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": "Результат показан пользователю.",
                        })
                        messages.append({"role": "assistant", "content": response.content})
                        messages.append({"role": "user", "content": tool_results})
                        return {"status": "completed", "result": result, "success": success}

                    # ── Local tools: ask_user / confirm_action ─────────────
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
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": f"Ответ пользователя: {answer}",
                        })
                        continue

                    # ── Local tool: extract_data → delegate to the sub-agent ─
                    if tool_use.name == "extract_data":
                        query = str(tool_use.input.get("query", ""))
                        await self._callback({
                            "step": step, "action": "subagent",
                            "details": f"Суб-агент читает страницу: {query[:80]}",
                        })
                        sub = ExtractionSubAgent(self._llm, mcp, mcp_tools)
                        try:
                            report = await sub.run(query)
                        except Exception as exc:  # noqa: BLE001
                            report = f"Ошибка суб-агента: {exc}"
                            logger.error("sub-agent failed: %s", exc)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": f"Отчёт суб-агента:\n{report}",
                        })
                        continue

                    # ── MCP tool call ─────────────────────────────────────
                    action = _tool_action(tool_use.name)
                    details = _tool_details(tool_use.name, tool_use.input)
                    await self._callback({"step": step, "action": action, "details": details})

                    try:
                        tool_result = await mcp.call_tool(tool_use.name, dict(tool_use.input))
                    except Exception as e:
                        tool_result = f"Ошибка инструмента {tool_use.name}: {e}"
                        logger.error("Tool %s failed: %s", tool_use.name, e)

                    # Truncate long tool results to save tokens.
                    if isinstance(tool_result, str) and len(tool_result) > TOOL_RESULT_MAX_LEN:
                        tool_result = (
                            tool_result[:TOOL_RESULT_MAX_LEN]
                            + f"\n... (обрезано, всего {len(tool_result)} символов)"
                        )

                    # Self-correction: nudge the model when it's stuck.
                    hint = corrector.hint_for(tool_use.name, dict(tool_use.input), tool_result)
                    if hint:
                        if isinstance(tool_result, str):
                            tool_result = f"{tool_result}\n\n{hint}"
                        else:  # image blocks (screenshot) — attach as text block
                            tool_result = list(tool_result) + [{"type": "text", "text": hint}]

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": tool_result,
                    })

                # Append the full exchange to message history.
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})

                # ── Context compression ───────────────────────────────────────
                if len(messages) > COMPRESS_THRESHOLD:
                    messages = self.messages = await self._compress(messages)

            # ── Max iterations reached ────────────────────────────────────────
            await self._callback(
                {
                    "step": step,
                    "action": "finish",
                    "details": f"Достигнут лимит итераций ({MAX_ITERATIONS}). Задача не завершена.",
                    "usage": self.usage_summary(),
                }
            )
            return {"status": "max_iterations_reached"}
