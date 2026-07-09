from mcp_instance import mcp, browser
from browser.snapshot import build_snapshot


@mcp.tool()
async def click(element_id: int) -> str:
    """
    Кликает по элементу с указанным номером из последнего snapshot (read_page).
    После клика возвращает обновлённый snapshot новой страницы или изменённого состояния.

    element_id — порядковый номер элемента в квадратных скобках [N] из read_page.
    Если номер устарел (страница изменилась) — вызови read_page снова и используй
    актуальные номера.

    Используй для нажатия кнопок, перехода по ссылкам, раскрытия меню.
    """
    try:
        tree = await browser.click_element(element_id)
        return build_snapshot(tree)
    except ValueError as e:
        return str(e)
    except Exception as e:
        return f"Ошибка при клике на элемент #{element_id}: {e}"
