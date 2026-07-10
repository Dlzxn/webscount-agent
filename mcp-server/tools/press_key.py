from mcp_instance import mcp, browser
from browser.snapshot import build_snapshot


@mcp.tool()
async def press_key(key: str) -> str:
    """
    Нажимает отдельную клавишу клавиатуры в текущем сфокусированном элементе.
    Возвращает snapshot после нажатия.

    key — название клавиши в формате Playwright: "Enter", "Escape", "Tab",
          "ArrowDown", "ArrowUp", "Backspace", "Space" и т.д.

    Используй для:
    - закрытия модальных окон (Escape);
    - перехода между полями формы (Tab);
    - подтверждения без submit-кнопки (Enter);
    - навигации по выпадающим спискам (ArrowDown/ArrowUp).
    """
    try:
        tree = await browser.press_key(key)
        return build_snapshot(tree)
    except Exception as e:
        return f"Ошибка при нажатии клавиши '{key}': {e}"
