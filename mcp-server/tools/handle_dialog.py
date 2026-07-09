from mcp_instance import mcp, browser


@mcp.tool()
async def handle_dialog(action: str) -> str:
    """
    Обрабатывает нативный браузерный диалог (alert, confirm, prompt),
    который блокирует страницу до явного ответа.

    action: "accept" — нажать OK / принять диалог,
            "dismiss" — нажать Отмена / закрыть диалог.

    Вызывай этот инструмент только когда браузер показал нативный системный диалог.
    Возвращает строку с результатом операции.
    """
    if action not in ("accept", "dismiss"):
        return "Ошибка: action должен быть 'accept' или 'dismiss'."
    try:
        return await browser.handle_dialog(action)
    except Exception as e:
        return f"Ошибка при обработке диалога: {e}"
