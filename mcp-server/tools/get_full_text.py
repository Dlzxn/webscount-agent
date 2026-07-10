from mcp_instance import mcp, browser


@mcp.tool()
async def get_full_text(max_chars: int = 5000) -> str:
    """
    Возвращает видимый текстовый контент текущей страницы (до max_chars символов).

    Используй этот инструмент когда read_page недостаточно и нужно прочитать
    реальное содержимое: цены, описания товаров, условия, длинные списки,
    текст статей. Не возвращает HTML — только чистый текст.

    max_chars — максимальное количество символов (по умолчанию 5000).
    """
    try:
        return await browser.get_full_text(max_chars=max_chars)
    except Exception as e:
        return f"Ошибка при получении текста страницы: {e}"
