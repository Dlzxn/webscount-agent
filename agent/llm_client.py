"""
Domain layer: Anthropic API communication only.
No knowledge of MCP, WebSocket, or browser.
"""

from __future__ import annotations

import asyncio

import anthropic

from agent.config import settings

SYSTEM_PROMPT = """\
Ты — браузерный агент-автоматизатор. Ты управляешь реальным браузером через набор инструментов \
и должен выполнить задачу пользователя.

КАК РАБОТАТЬ:
1. Начни с navigate чтобы открыть нужный сайт, если он ещё не открыт.
2. Используй read_page чтобы увидеть текущую страницу — ты получишь пронумерованный список \
интерактивных элементов (кнопки, ссылки, поля ввода). Только эти элементы доступны для \
взаимодействия.
3. Для чтения текстового содержимого (цены, описания, статьи, таблицы) используй get_full_text.
4. Перед каждым вызовом инструмента КРАТКО напиши (1–2 предложения) что именно ты собираешься \
сделать и что ожидаешь увидеть в ответе. Это обязательно.
5. Когда задача выполнена — вызови finish с итоговым результатом.
6. Если не можешь продолжить без ответа пользователя — вызови ask_user с конкретным вопросом.

ПРАВИЛА:
- Номера элементов актуальны только до следующего действия, меняющего страницу. \
Всегда вызывай read_page после навигации или клика по ссылке.
- Если действие не дало ожидаемого результата — пересмотри подход, не повторяй то же самое.
- Используй get_current_state чтобы убедиться, что ты находишься на правильной странице.
- Не придумывай номера элементов наугад — бери только из последнего read_page.
"""


class AgentLLM:
    def __init__(self) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._model = settings.anthropic_model

    async def get_next_action(
        self,
        messages: list[dict],
        tools: list[dict],
    ) -> anthropic.types.Message:
        """Single LLM call. Retries once on rate-limit or timeout."""
        for attempt in range(2):
            try:
                return await self._client.messages.create(
                    model=self._model,
                    max_tokens=1024,
                    system=SYSTEM_PROMPT,
                    messages=messages,
                    tools=tools,  # type: ignore[arg-type]
                )
            except (anthropic.RateLimitError, anthropic.APITimeoutError):
                if attempt == 0:
                    await asyncio.sleep(2)
                else:
                    raise

        raise RuntimeError("Unreachable")  # pragma: no cover


def extract_tool_use(
    response: anthropic.types.Message,
) -> anthropic.types.ToolUseBlock | None:
    for block in response.content:
        if block.type == "tool_use":
            return block
    return None


def extract_text(response: anthropic.types.Message) -> str:
    return " ".join(
        block.text
        for block in response.content
        if block.type == "text"
    ).strip()
