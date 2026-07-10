from mcp.server.fastmcp import Image

from mcp_instance import mcp, browser


@mcp.tool()
async def screenshot() -> Image:
    """
    Делает скриншот видимой области текущей вкладки и возвращает его как
    изображение — ты УВИДИШЬ страницу так, как её видит пользователь.

    ⚠️ КРАЙНЯЯ МЕРА: это самый дорогой инструмент (изображение расходует
    очень много токенов). Вызывай ТОЛЬКО когда текстовые инструменты не
    помогают понять страницу: canvas-виджеты, карты, графики, капча,
    подозрение на сломанную вёрстку или перекрывающий контент оверлей.
    Сначала ВСЕГДА пробуй read_page и get_full_text.
    """
    data = await browser.screenshot()
    return Image(data=data, format="jpeg")
