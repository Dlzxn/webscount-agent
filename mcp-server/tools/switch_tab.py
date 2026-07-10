from mcp_instance import mcp, browser
from browser.snapshot import build_snapshot


@mcp.tool()
async def switch_tab(index: int) -> str:
    """
    Переключает активную вкладку браузера на вкладку с указанным номером.
    Все последующие инструменты (read_page, click, type_text...) будут
    работать именно с ней. Возвращает snapshot выбранной вкладки.

    index — номер вкладки из list_tabs (нумерация с 1).

    Используй когда после клика открылась новая вкладка, а нужно вернуться
    к предыдущей (например, новая вкладка оказалась рекламой), или чтобы
    перейти на любую другую открытую вкладку.
    """
    try:
        tree = await browser.switch_tab(index)
        return build_snapshot(tree)
    except ValueError as e:
        return str(e)
    except Exception as e:
        return f"Ошибка при переключении на вкладку #{index}: {e}"
