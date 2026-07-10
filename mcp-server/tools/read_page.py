from mcp_instance import mcp, browser
from browser.snapshot import build_snapshot


@mcp.tool()
async def read_page() -> str:
    """
    Возвращает отфильтрованный snapshot текущей страницы:
    только интерактивные элементы (кнопки, ссылки, поля ввода, выпадающие списки)
    с порядковыми номерами, плюс короткие заголовки для навигационного контекста.

    НЕ возвращает длинный текстовый контент (описания, статьи, таблицы цен).
    Используй этот инструмент чтобы понять структуру страницы и получить номера
    элементов для последующих click, type_text, select_option.

    Вызывай read_page перед каждым click/type_text, если страница могла измениться.
    """
    try:
        tree = await browser.get_accessibility_tree()
        return build_snapshot(tree)
    except Exception as e:
        return f"Ошибка при чтении страницы: {e}"
