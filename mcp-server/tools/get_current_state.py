import json

from mcp_instance import mcp, browser


@mcp.tool()
async def get_current_state() -> str:
    """
    Возвращает JSON-строку с текущим состоянием браузера:
    {"url": "https://...", "title": "Название страницы", "tabs_open": N}.
    Если с прошлого вызова сменилась активная вкладка — добавляется поле "notice".

    Используй этот инструмент чтобы явно проверить, на какой странице
    сейчас находится браузер — особенно после переходов, редиректов
    или клика по ссылке, чтобы убедиться что навигация прошла правильно.
    """
    try:
        state = await browser.get_state()
        return json.dumps(state, ensure_ascii=False)
    except Exception as e:
        return f"Ошибка при получении состояния браузера: {e}"
