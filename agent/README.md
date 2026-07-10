# Agent

LLM-оркестратор: получает задачу от расширения, ведёт цикл «думать → вызвать инструмент →
получить результат» через Claude и стримит прогресс обратно по WebSocket. Сам браузером не
управляет — все действия идут через `mcp-server/` по MCP-протоколу.

Порт: **8001**. Точка входа: `main.py` (в корне проекта) или `python -m agent.main`.

## Файлы

| Файл | Роль |
|---|---|
| `config.py` | Настройки из `.env` (API-ключ, модель, URL MCP-сервера) |
| `llm_client.py` | Обёртка над Anthropic API + системный промпт агента |
| `local_tools.py` | Схемы локальных инструментов: `finish`, `ask_user`, `confirm_action` |
| `mcp_client.py` | Клиент MCP-сервера (streamable-http) |
| `loop.py` | `AgentSession` — главный цикл агента |
| `api.py` | FastAPI: `GET /health`, `WebSocket /ws` |

Подробности об архитектуре и потоке данных — в [README корня проекта](../README.md).
