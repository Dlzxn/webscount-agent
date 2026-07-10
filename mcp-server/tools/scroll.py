from mcp_instance import mcp, browser
from browser.snapshot import build_snapshot


@mcp.tool()
async def scroll(direction: str, amount: str) -> str:
    """
    Прокручивает текущую страницу и возвращает обновлённый snapshot.

    direction: "up" — прокрутить вверх, "down" — прокрутить вниз.
    amount: "page" — прокрутить на один экран,
            "bottom" — прокрутить до самого низа страницы
            (полезно для страниц с infinite scroll чтобы подгрузить новый контент).

    Используй этот инструмент когда нужные элементы не попали в текущий snapshot,
    или когда нужно подгрузить больше элементов в бесконечной ленте.
    """
    if direction not in ("up", "down"):
        return "Ошибка: direction должен быть 'up' или 'down'."
    if amount not in ("page", "bottom"):
        return "Ошибка: amount должен быть 'page' или 'bottom'."
    try:
        tree = await browser.scroll(direction, amount)
        return build_snapshot(tree)
    except Exception as e:
        return f"Ошибка при прокрутке: {e}"
