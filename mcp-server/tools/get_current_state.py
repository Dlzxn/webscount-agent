import json

from mcp_instance import mcp, browser


@mcp.tool()
async def get_current_state() -> str:
    """
    Возвращает JSON-строку с текущим URL и заголовком страницы:
    {"url": "https://...", "title": "Название страницы"}.

    Используй этот инструмент чтобы явно проверить, на какой странице
    сейчас находится браузер — особенно после переходов, редиректов
    или клика по ссылке, чтобы убедиться что навигация прошла правильно.
    """
    try:
        url = await browser.get_url()
        title = await browser.get_title()
        return json.dumps({"url": url, "title": title}, ensure_ascii=False)
    except Exception as e:
        return f"Ошибка при получении состояния браузера: {e}"
