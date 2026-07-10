# WebScout Agent

AI-агент для автоматизации браузера. Пользователь описывает задачу на естественном языке в Chrome-расширении, Claude выполняет её в реальном браузере через Playwright, а прогресс стримится обратно в расширение в реальном времени.

## Архитектура

```
┌─────────────────────┐      WebSocket       ┌──────────────────────┐
│  Chrome Extension   │ ◄──────────────────► │    Agent (FastAPI)   │
│  extension/         │   task + status +    │    agent/            │
│  popup.html + .js   │   human-in-the-loop  │    :8001             │
└─────────────────────┘                      └──────────┬───────────┘
                                                        │  MCP (streamable-http)
                                                        ▼
                                             ┌──────────────────────┐
                                             │   MCP Server         │
                                             │   mcp-server/        │
                                             │   :8000              │
                                             └──────────┬───────────┘
                                                        │  Playwright
                                                        ▼
                                                  [ Chromium ]
```

**Три компонента:**

| Компонент | Директория | Порт | Роль |
|---|---|---|---|
| Chrome Extension | `extension/` | — | UI: ввод задачи, лог шагов, human-in-the-loop |
| Agent | `agent/` + `main.py` | 8001 | LLM-оркестратор (Claude) + WebSocket API |
| MCP Server | `mcp-server/` | 8000 | 13 браузерных инструментов через Playwright |

## Ключевые возможности

- **CDP-подключение** — агент подключается к вашему уже запущенному браузеру через Chrome DevTools Protocol и работает в той же вкладке, что и вы. Логины, cookies, сессии — всё сохраняется.
- **Human-in-the-loop** — агент может задать вопрос (`ask_user`) или запросить подтверждение (`confirm_action`) перед важными действиями (оплата, отправка формы). Всё через WebSocket, без перезагрузки.
- **MCP-протокол** — браузерные инструменты выделены в отдельный MCP-сервер. Агент и инструменты полностью декаплены.
- **Контекстная компрессия с суммаризацией** — при длинных задачах средние шаги сжимаются: дешёвая модель (Haiku) делает сводку фактов, вместо того чтобы их выбрасывать. История и статичный префикс кэшируются (prompt caching).
- **Фоновое выполнение** — WebSocket живёт в service worker расширения: задача продолжается при закрытом попапе, по завершении приходит нотификация. Кнопка «Остановить» отменяет задачу.
- **Статистика токенов** — по завершении задачи в лог выводится расход токенов, доля кэша и оценка стоимости.
- **iframe и скачивания** — snapshot включает элементы внутри iframe (платёжные формы, виджеты), скачивания файлов явно репортятся агенту.
- **Docker** — полная контейнеризация с headless Chromium.

## Быстрый старт

### Локальный запуск

```bash
# 1. Зависимости
uv sync
uv run playwright install chromium

# 2. Конфигурация
cp .env.example .env
# Заполни ANTHROPIC_API_KEY в .env

# 3. Запуск MCP-сервера (в отдельном терминале)
cd mcp-server
uv run python server.py

# 4. Запуск агента (в отдельном терминале)
uv run python main.py
```

### Запуск браузера с CDP (рекомендуется)

Запусти `start_browser.bat` — он откроет Chrome/Yandex/Edge с `--remote-debugging-port=9222` и автоматически загрузит расширение. Агент подключится к этому браузеру через CDP и будет действовать в вашем окне.

Если CDP недоступен, агент запустит собственный Chromium с расширением.

### Docker

```bash
echo ANTHROPIC_API_KEY=sk-ant-... > .env
docker-compose up --build
```

| Сервис | URL | Описание |
|---|---|---|
| MCP Server | `localhost:8000` | Headless Chromium |
| Agent | `localhost:8001` | WebSocket API |
| Extension | `localhost:8080` | Статика расширения (для ручной установки) |

### Установка расширения

1. Открой `chrome://extensions/`
2. Включи **Developer mode**
3. **Load unpacked** → выбери папку `extension/`

## Конфигурация

| Переменная | По умолчанию | Описание |
|---|---|---|
| `ANTHROPIC_API_KEY` | *обязательно* | API-ключ Anthropic |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-6` | Основная модель Claude |
| `ANTHROPIC_SMALL_MODEL` | `claude-haiku-4-5-20251001` | Дешёвая модель для сжатия истории |
| `MCP_SERVER_URL` | `http://localhost:8000/mcp` | URL MCP-сервера |
| `BROWSER_CDP_URL` | `http://127.0.0.1:9222` | CDP-эндпоинт браузера |
| `HEADLESS` | `false` | Headless-режим (для Docker) |
| `MCP_HOST` | `127.0.0.1` | Bind-адрес MCP-сервера |

## MCP-инструменты (13 шт.)

Каждый инструмент — отдельный файл в `mcp-server/tools/`, зарегистрированный через `@mcp.tool()`.

| Инструмент | Описание |
|---|---|
| `navigate(url)` | Открывает URL, возвращает snapshot |
| `go_back()` | Кнопка «Назад» |
| `read_page()` | Snapshot интерактивных элементов с номерами `[N]` |
| `get_full_text()` | Весь видимый текст страницы |
| `get_current_state()` | Текущий URL + заголовок + число вкладок (JSON) |
| `list_tabs()` | Список открытых вкладок с пометкой активной |
| `switch_tab(index)` | Переключение активной вкладки по номеру из `list_tabs` |
| `click(element_id)` | Клик по элементу `[N]` |
| `type_text(element_id, text, submit)` | Ввод текста, опционально + Enter |
| `select_option(element_id, option_label)` | Выбор в `<select>` по видимому тексту |
| `press_key(key)` | Нажатие клавиши (Enter, Escape, Tab...) |
| `scroll(direction, amount)` | Прокрутка (up/down, page/bottom) |
| `handle_dialog(action)` | Обработка нативных диалогов (accept/dismiss) |

**Локальные инструменты агента** (не уходят на MCP-сервер):

| Инструмент | Описание |
|---|---|
| `finish(result, success)` | Завершение задачи |
| `ask_user(question)` | Вопрос пользователю (блокирует цикл до ответа) |
| `confirm_action(action_description)` | Подтверждение перед важным действием |

## Поток данных

```
1. Пользователь вводит задачу в popup → WS send {"task": "..."}

2. AgentSession.run():
   a. MCPToolClient подключается к MCP-серверу (streamable-http)
   b. Получает 13 MCP-инструментов + 3 локальных
   c. Цикл (до 30 итераций):
      → WS {"action": "thinking"}        → 💭 в логе
      → Claude выбирает инструмент
      → WS {"action": "navigate/click/..."} → 🧭🖱️⌨️ в логе
      → MCP call_tool → Playwright → результат в messages
      → если confirm_action/ask_user:
        → WS {"action": "confirm_request/ask_user"} → ⚠️❓ в логе
        → ждём {"answer": "..."} от пользователя по WS
      → при >20 сообщений: компрессия контекста

3. Claude вызывает finish → WS {"action": "finish"} → ✅ в логе
```

## Snapshot-формат

Агент видит страницу как пронумерованный список элементов:

```
# Заголовок страницы

[1] link: Главная
[2] button: Войти
[3] input[text]: Email  (текущее значение: "user@example.com")
[4] select: Страна
[5] textarea: Комментарий
```

Номера `[N]` — это `element_id` для `click`, `type_text`, `select_option`. Номера актуальны только до следующего действия, меняющего страницу.

## Структура проекта

```
webscount-agent/
├── main.py                        # Точка входа агента (uvicorn :8001)
├── pyproject.toml                 # Зависимости (uv)
├── start_browser.bat              # Запуск Chrome с CDP + расширением
├── Dockerfile                     # Образ для Docker
├── docker-compose.yml             # Оркестрация трёх сервисов
│
├── agent/                         # LLM-оркестратор
│   ├── config.py                  # Настройки из .env
│   ├── llm_client.py              # Обёртка над Anthropic API + системный промпт
│   ├── local_tools.py             # Схемы finish / ask_user / confirm_action
│   ├── mcp_client.py              # MCP-клиент (streamable-http)
│   ├── loop.py                    # Главный цикл агента (AgentSession)
│   └── api.py                     # FastAPI: WebSocket /ws, GET /health
│
├── mcp-server/                    # Браузерные инструменты (MCP)
│   ├── server.py                  # Точка входа (uvicorn :8000)
│   ├── mcp_instance.py            # Синглтоны FastMCP + BrowserSession
│   ├── browser/
│   │   ├── session.py             # BrowserSession — обёртка над Playwright
│   │   └── snapshot.py            # Форматирование дерева элементов в текст
│   └── tools/                     # 13 @mcp.tool() инструментов
│       ├── navigate.py
│       ├── click.py
│       ├── type_text.py
│       ├── read_page.py
│       ├── get_full_text.py
│       ├── get_current_state.py
│       ├── scroll.py
│       ├── select_option.py
│       ├── press_key.py
│       ├── go_back.py
│       ├── handle_dialog.py
│       ├── list_tabs.py
│       └── switch_tab.py
│
└── extension/                     # Chrome Extension (Manifest V3)
    ├── manifest.json
    ├── popup.html                 # UI попапа
    ├── popup.js                   # WS-клиент + human-in-the-loop
    └── styles.css                 # Тёмная тема
```

## Режимы работы браузера

| Режим | Как запускается | Расширение | Cookies/Логины |
|---|---|---|---|
| **CDP** (рекомендуется) | `start_browser.bat` | Загружается автоматически | Сохраняются между сессиями |
| **Fallback** | Автоматически, если CDP недоступен | Загружается в Chromium | Сохраняются (persistent context) |
| **Docker headless** | `docker-compose up` | Нет (ставится вручную в Chrome) | Изолированы в контейнере |

## Известные ограничения

- **Одна задача одновременно** — WebSocket-сессия одна на подключение.
- **Контекстное окно** — компрессия отбрасывает средние шаги при длинных задачах.
- **Windows** — MCP-сервер использует ProactorEventLoop (Playwright требует его для `create_subprocess_exec`).

## Стек

- **LLM**: Anthropic Claude (через `anthropic` SDK)
- **Протокол**: MCP (Model Context Protocol) — `mcp` SDK, streamable-http транспорт
- **Браузер**: Playwright + Chromium
- **API**: FastAPI + WebSocket
- **Менеджер пакетов**: uv

## Лицензия

Apache License 2.0 — см. [LICENSE](LICENSE).
