from mcp_instance import mcp, browser


@mcp.tool()
async def get_full_text() -> str:
    """
    Возвращает весь видимый текстовый контент текущей страницы без обрезки.

    Используй этот инструмент когда read_page недостаточно и нужно прочитать
    реальное содержимое: цены, описания товаров, условия, длинные списки,
    текст статей. Не возвращает HTML — только чистый текст.
    """
    try:
        return await browser.get_full_text()
    except Exception as e:
        return f"Ошибка при получении текста страницы: {e}"
