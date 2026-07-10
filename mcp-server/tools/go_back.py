from mcp_instance import mcp, browser
from browser.snapshot import build_snapshot


@mcp.tool()
async def go_back() -> str:
    """
    Возвращает браузер на предыдущую страницу в истории (аналог кнопки «Назад»).
    Вызывай когда нужно вернуться на страницу, которая была открыта до текущей.
    Возвращает snapshot новой текущей страницы.
    """
    try:
        tree = await browser.go_back()
        return build_snapshot(tree)
    except Exception as e:
        return f"Ошибка при возврате назад: {e}"
