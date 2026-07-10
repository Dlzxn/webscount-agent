"""
Domain layer: Anthropic API communication only.
No knowledge of MCP, WebSocket, or browser.
"""

from __future__ import annotations

import asyncio
import json
import logging

import anthropic

from agent.config import settings

logger = logging.getLogger("agent.llm_client")

# USD per 1M tokens: (input, output, cache_write, cache_read).
# Matched by substring of the model id; unknown models get no cost estimate.
_PRICES_PER_MTOK: dict[str, tuple[float, float, float, float]] = {
    "opus": (15.0, 75.0, 18.75, 1.5),
    "sonnet": (3.0, 15.0, 3.75, 0.3),
    "haiku": (1.0, 5.0, 1.25, 0.1),
}


def _price_for(model: str) -> tuple[float, float, float, float] | None:
    for key, prices in _PRICES_PER_MTOK.items():
        if key in model:
            return prices
    return None

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
6. Ты работаешь в паре с человеком (human in the loop): он видит твой прогресс и вполне может \
ответить на вопрос или помочь, если ты сам не можешь разобраться — застрял после нескольких \
попыток, нужна капча, логин, выбор между равнозначными вариантами. Вызови ask_user с конкретным \
вопросом — это лучше, чем провалить задачу. Но не обращайся часто: сначала честно попробуй \
разобраться самостоятельно.
7. ПЕРЕД важным или необратимым действием ОБЯЗАТЕЛЬНО вызови confirm_action и дождись \
подтверждения: оплата, оформление или подтверждение заказа, отправка форм с личными данными, \
удаление данных, отправка сообщений от имени пользователя. В описании укажи все ключевые \
детали (товар, сумма, адрес, получатель). Если пользователь отказал — не выполняй действие \
и уточни, что делать дальше.

ПРАВИЛА:
- Номера элементов актуальны только до следующего действия, меняющего страницу. \
Всегда вызывай read_page после навигации или клика по ссылке.
- Если действие не дало ожидаемого результата — пересмотри подход, не повторяй то же самое.
- Используй get_current_state чтобы убедиться, что ты находишься на правильной странице.
- Не придумывай номера элементов наугад — бери только из последнего read_page.
- Если ответ инструмента начинается с предупреждения «Активная вкладка сменилась» — значит \
клик открыл новую вкладку и все инструменты теперь работают с ней. Если новая вкладка — то, \
что тебе нужно, продолжай в ней; если нет (например реклама) — вернись через list_tabs и \
switch_tab.
- ЭКОНОМЬ ТОКЕНЫ: сначала ищи нужную информацию через read_page. \
Вызывай get_full_text ТОЛЬКО когда read_page не содержит нужных данных (цены, описания, \
длинные списки). Не вызывай get_full_text повторно на той же странице — кешируй результат.
- screenshot — КРАЙНЯЯ МЕРА, самый дорогой инструмент. Используй его только когда текстовые \
инструменты не дают понять, что происходит на странице: canvas/карты/графики, капча, \
подозрение на оверлей или сломанную вёрстку, элементы ведут себя не так, как ожидается. \
Никогда не начинай со screenshot и не вызывай его повторно без необходимости.
"""


# Cache breakpoint here covers the whole static prefix (tools + system):
# built once, identical on every call.
_SYSTEM_BLOCKS = [
    {
        "type": "text",
        "text": SYSTEM_PROMPT,
        "cache_control": {"type": "ephemeral"},
    }
]


def _with_cache_breakpoint(messages: list[dict]) -> list[dict]:
    """
    Copy of messages with a cache_control breakpoint on the last content block
    of the last message (always a user message in our loop). Each turn extends
    the previously cached prefix, so the whole conversation history is read
    from cache (~10% of input price) instead of being re-billed in full.
    Originals are never mutated, so stale breakpoints don't accumulate.
    """
    if not messages:
        return messages
    last = messages[-1]
    content = last["content"]
    if isinstance(content, str):
        blocks: list = [
            {"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}
        ]
    elif isinstance(content, list) and content and isinstance(content[-1], dict):
        blocks = content[:-1] + [
            {**content[-1], "cache_control": {"type": "ephemeral"}}
        ]
    else:
        return messages
    return messages[:-1] + [{"role": last["role"], "content": blocks}]


def _render_for_summary(messages: list[dict], max_chars: int = 6000) -> str:
    """Flatten a slice of agent history into plain text for the summarizer."""
    lines: list[str] = []
    for msg in messages:
        content = msg["content"]
        if isinstance(content, str):
            lines.append(f"{msg['role']}: {content[:300]}")
            continue
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "tool_result":
                    c = block.get("content", "")
                    if isinstance(c, list):  # screenshot — don't dump base64
                        lines.append("результат: [скриншот страницы]")
                    else:
                        lines.append(f"результат: {str(c)[:300]}")
                elif block.get("type") == "text":
                    lines.append(f"{msg['role']}: {block['text'][:300]}")
            else:  # anthropic SDK block
                btype = getattr(block, "type", "")
                if btype == "text":
                    lines.append(f"{msg['role']}: {block.text[:300]}")
                elif btype == "tool_use":
                    args = json.dumps(block.input, ensure_ascii=False)[:200]
                    lines.append(f"вызов: {block.name}({args})")
    return "\n".join(lines)[:max_chars]


class AgentLLM:
    def __init__(self) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._model = settings.anthropic_model
        self._small_model = settings.anthropic_small_model
        self.usage = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
        self._cost_usd = 0.0
        self._cost_known = True

    def _track_usage(self, response: anthropic.types.Message, model: str) -> None:
        u = response.usage
        parts = {
            "input": u.input_tokens or 0,
            "output": u.output_tokens or 0,
            "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0,
            "cache_write": getattr(u, "cache_creation_input_tokens", 0) or 0,
        }
        for k, v in parts.items():
            self.usage[k] += v
        prices = _price_for(model)
        if prices is None:
            self._cost_known = False
        else:
            p_in, p_out, p_write, p_read = prices
            self._cost_usd += (
                parts["input"] * p_in
                + parts["output"] * p_out
                + parts["cache_write"] * p_write
                + parts["cache_read"] * p_read
            ) / 1_000_000
        logger.info(
            "tokens[%s]: in=%d out=%d cache_read=%d cache_write=%d",
            model, parts["input"], parts["output"],
            parts["cache_read"], parts["cache_write"],
        )

    def usage_summary(self) -> dict:
        """Cumulative tokens + cost estimate for everything this LLM did."""
        return {
            **self.usage,
            "cost_usd": round(self._cost_usd, 4) if self._cost_known else None,
        }

    async def summarize_steps(self, old_summary: str, dropped: list[dict]) -> str:
        """
        Compress dropped middle steps into a short factual summary using the
        cheap model, so context compression keeps information instead of
        discarding it. Raises on failure — the caller degrades to plain drop.
        """
        rendered = _render_for_summary(dropped)
        prompt = (
            "Ниже — журнал шагов браузерного AI-агента, которые сейчас будут "
            "удалены из его контекста. Сожми их в краткую сводку (максимум "
            "10 строк): какие страницы посещены, какие действия выполнены, "
            "какие ВАЖНЫЕ ФАКТЫ найдены (цены, названия, номера, ответы "
            "пользователя). Только факты, без рассуждений.\n\n"
            + (f"Предыдущая сводка (объедини с ней):\n{old_summary}\n\n" if old_summary else "")
            + f"Журнал:\n{rendered}"
        )
        response = await self._client.messages.create(
            model=self._small_model,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        self._track_usage(response, self._small_model)
        return extract_text(response)

    async def get_next_action(
        self,
        messages: list[dict],
        tools: list[dict],
    ) -> anthropic.types.Message:
        """Single LLM call. Retries up to 3 times with exponential backoff.
        Caches the static prefix (tools + system) and the conversation history."""
        cached_messages = _with_cache_breakpoint(messages)
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = await self._client.messages.create(
                    model=self._model,
                    max_tokens=1024,
                    system=_SYSTEM_BLOCKS,
                    messages=cached_messages,
                    tools=tools,  # type: ignore[arg-type]
                )
                self._track_usage(response, self._model)
                return response
            except (anthropic.RateLimitError, anthropic.APITimeoutError) as e:
                last_error = e
                wait = 2 ** (attempt + 1)  # 2s, 4s, 8s
                logger.warning("LLM rate-limit/timeout, retry %d/3 in %ds", attempt + 1, wait)
                await asyncio.sleep(wait)
            except anthropic.APIError as e:
                last_error = e
                if attempt < 2:
                    wait = 2 ** (attempt + 1)
                    logger.warning("LLM API error, retry %d/3 in %ds: %s", attempt + 1, wait, e)
                    await asyncio.sleep(wait)
                else:
                    raise

        raise RuntimeError(f"LLM call failed after 3 retries: {last_error}")


def extract_tool_use(
    response: anthropic.types.Message,
) -> anthropic.types.ToolUseBlock | None:
    """Extract the first tool_use block. Returns None if no tool call."""
    for block in response.content:
        if block.type == "tool_use":
            return block
    return None


def extract_all_tool_uses(
    response: anthropic.types.Message,
) -> list[anthropic.types.ToolUseBlock]:
    """Extract all tool_use blocks from response (for parallel tool calls)."""
    return [block for block in response.content if block.type == "tool_use"]


def extract_text(response: anthropic.types.Message) -> str:
    return " ".join(
        block.text
        for block in response.content
        if block.type == "text"
    ).strip()
