from mcp_instance import mcp, browser
from browser.snapshot import build_snapshot


@mcp.tool()
async def select_option(element_id: int, option_label: str) -> str:
    """
    Выбирает опцию в выпадающем списке (<select>) с указанным номером из snapshot.
    Использует нативный метод Playwright select_option по видимому тексту опции —
    это надёжнее чем эмулировать клик по <select>, который ведёт себя по-разному
    в разных браузерах.
    Возвращает snapshot после выбора.

    element_id — номер элемента select из read_page.
    option_label — точный видимый текст опции которую нужно выбрать.
    """
    try:
        tree = await browser.select_option_element(element_id, option_label)
        return build_snapshot(tree)
    except ValueError as e:
        return str(e)
    except Exception as e:
        return (
            f"Ошибка при выборе опции '{option_label}' "
            f"в элементе #{element_id}: {e}"
        )
