from mcp_instance import mcp, browser
from browser.snapshot import build_snapshot


@mcp.tool()
async def navigate(url: str) -> str:
    """
    Открывает указанный URL в браузере и возвращает snapshot страницы после загрузки.
    Вызывай этот инструмент когда нужно перейти на новую страницу или сайт.
    url должен быть полным адресом, включая схему (https://...).
    """
    try:
        tree = await browser.goto(url)
        return build_snapshot(tree)
    except Exception as e:
        return f"Ошибка при переходе на {url}: {e}"
