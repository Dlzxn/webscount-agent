# MCP Server

Браузерные инструменты, отданные наружу по протоколу MCP (streamable-http). Управляет одной
страницей Playwright: подключается к уже запущенному браузеру пользователя через CDP, либо
поднимает собственный Chromium как fallback. О самом агенте и LLM ничего не знает — только
принимает вызовы инструментов и возвращает текстовые snapshot'ы страницы.

Порт: **8000**. Точка входа: `server.py` (или `start.py` для запуска из этой директории).

## Структура

| Путь | Роль |
|---|---|
| `mcp_instance.py` | Общие синглтоны `FastMCP` и `BrowserSession` |
| `browser/session.py` | `BrowserSession` — обёртка над Playwright (CDP/fallback, клики, ввод, snapshot) |
| `browser/snapshot.py` | Форматирование дерева элементов в компактный текст для LLM |
| `tools/` | 11 инструментов, каждый — отдельный файл с `@mcp.tool()` |

## Инструменты

`navigate`, `go_back`, `read_page`, `get_full_text`, `get_current_state`, `click`, `type_text`,
`select_option`, `press_key`, `scroll`, `handle_dialog` — полное описание каждого в
[README корня проекта](../README.md#mcp-инструменты-11-шт).
