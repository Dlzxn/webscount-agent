from mcp_instance import mcp, browser


@mcp.tool()
async def list_tabs() -> str:
    """
    Возвращает список всех открытых вкладок браузера: номер, заголовок, URL
    и пометку какая из них активная (с ней работают все остальные инструменты).

    Используй вместе со switch_tab когда нужно осознанно переключиться между
    вкладками — например, после клика открылась новая вкладка, а тебе нужно
    вернуться к предыдущей.
    """
    try:
        tabs = await browser.list_tabs()
        lines = [f"Открытые вкладки ({len(tabs)}):"]
        for t in tabs:
            mark = "  ← активная" if t["active"] else ""
            title = t["title"] or "(без названия)"
            lines.append(f"[{t['index']}] {title} — {t['url']}{mark}")
        return "\n".join(lines)
    except Exception as e:
        return f"Ошибка при получении списка вкладок: {e}"
