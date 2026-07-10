"""
Sub-agent architecture: narrow specialists the orchestrator delegates to.

ExtractionSubAgent — a read-only agent on the cheap model with its own small
tool loop. The main agent calls it via the extract_data tool; the sub-agent
reads the current page itself (scrolling if needed) and returns only the
requested facts. The orchestrator's context receives a compact report instead
of pages of raw text — and the reading is billed at the cheap model's price.
"""

from __future__ import annotations

import logging

from agent.llm_client import AgentLLM, extract_all_tool_uses, extract_text
from agent.mcp_client import MCPToolClient

logger = logging.getLogger("agent.subagent")

MAX_STEPS = 5
RESULT_MAX_LEN = 2000  # cap on what flows back into the orchestrator's context

# The sub-agent must observe, never act: no clicks, no typing, no navigation.
READONLY_TOOLS = {"read_page", "get_full_text", "get_current_state", "scroll"}

SUB_SYSTEM_PROMPT = """\
Ты — суб-агент чтения веб-страниц. Главный агент делегировал тебе вопрос про \
СТРАНИЦУ, ОТКРЫТУЮ СЕЙЧАС в браузере. Твоя задача — найти ответ и вернуть \
только факты.

ПРАВИЛА:
- Тебе доступны только инструменты чтения: read_page, get_full_text, \
get_current_state, scroll. Ты не можешь кликать, вводить текст или переходить \
по ссылкам.
- Начни с get_full_text (или read_page, если нужна структура). Если нужной \
информации не видно — прокрути страницу (scroll) и прочитай ещё раз. \
У тебя максимум {max_steps} вызовов инструментов.
- Когда собрал данные — ответь ОБЫЧНЫМ ТЕКСТОМ без вызова инструментов: \
кратко, только запрошенные факты (названия, цены, числа, списки), без \
рассуждений и пересказа лишнего.
- Если данных на странице нет — прямо скажи, что именно не найдено и что \
на странице есть вместо этого (одной-двумя строками).
""".format(max_steps=MAX_STEPS)


class ExtractionSubAgent:
    """Single-use: one delegated query against the current page."""

    def __init__(self, llm: AgentLLM, mcp: MCPToolClient, mcp_tools: list[dict]) -> None:
        self._llm = llm
        self._mcp = mcp
        self._tools = [t for t in mcp_tools if t["name"] in READONLY_TOOLS]

    async def run(self, query: str) -> str:
        logger.info("sub-agent query: %s", query[:80])
        messages: list[dict] = [{"role": "user", "content": query}]

        for _ in range(MAX_STEPS):
            response = await self._llm.small_call(SUB_SYSTEM_PROMPT, messages, self._tools)
            tool_uses = extract_all_tool_uses(response)

            if not tool_uses:  # plain-text answer — the report
                return self._finalize(extract_text(response))

            results = []
            for tu in tool_uses:
                try:
                    result = await self._mcp.call_tool(tu.name, dict(tu.input))
                except Exception as exc:  # noqa: BLE001
                    result = f"Ошибка инструмента {tu.name}: {exc}"
                if not isinstance(result, str):
                    result = "(изображения недоступны суб-агенту)"
                elif len(result) > 8000:
                    result = result[:8000] + "\n…(обрезано)"
                results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": result,
                })
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": results})

        # Step budget exhausted — force a final text answer (no tools offered).
        messages[-1]["content"] = list(messages[-1]["content"]) + [{
            "type": "text",
            "text": "Лимит шагов исчерпан. Дай финальный ответ по уже собранным данным.",
        }]
        response = await self._llm.small_call(SUB_SYSTEM_PROMPT, messages, tools=None)
        return self._finalize(extract_text(response))

    @staticmethod
    def _finalize(answer: str) -> str:
        answer = answer.strip() or "(суб-агент не дал ответа)"
        if len(answer) > RESULT_MAX_LEN:
            answer = answer[:RESULT_MAX_LEN] + "\n…(отчёт обрезан)"
        return answer
