from mcp_instance import mcp, browser
from browser.snapshot import build_snapshot


@mcp.tool()
async def type_text(element_id: int, text: str, submit: bool = False) -> str:
    """
    Вводит текст в поле ввода с указанным номером из последнего snapshot (read_page).
    Если submit=True — сразу нажимает Enter после ввода (удобно для форм поиска
    чтобы одним вызовом ввести запрос и отправить форму).
    Возвращает snapshot после ввода.

    element_id — номер поля ввода (input, textarea) из read_page.
    text — строка для ввода (заменяет текущее значение поля).
    submit — True чтобы нажать Enter после ввода, False (по умолчанию) чтобы просто ввести.
    """
    try:
        tree = await browser.fill_element(element_id, text)
        if submit:
            tree = await browser.press_key("Enter")
        return build_snapshot(tree)
    except ValueError as e:
        return str(e)
    except Exception as e:
        return f"Ошибка при вводе текста в элемент #{element_id}: {e}"
