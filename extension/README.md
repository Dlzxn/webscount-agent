# Extension

Chrome-расширение (Manifest V3) — UI поверх агента. Попап отправляет задачу на `agent/` по
WebSocket, стримит лог шагов в реальном времени и рендерит human-in-the-loop запросы
(`confirm_action`, `ask_user`) как интерактивные блоки с кнопками/полем ввода.

Никакой логики агента здесь нет — только отображение и пересылка ответов пользователя по тому
же WebSocket-соединению.

## Файлы

| Файл | Роль |
|---|---|
| `manifest.json` | Manifest V3: попап, service worker, разрешения |
| `background.js` | Service worker: владеет WebSocket — задачи живут при закрытом попапе, нотификации |
| `popup.html` | Разметка попапа |
| `popup.js` | Представление: лог шагов, human-in-the-loop блоки, кнопки запуска/стопа |
| `styles.css` | Тёмная тема |

## Установка

`chrome://extensions/` → Developer mode → Load unpacked → выбрать эту папку.

Для работы в текущем окне браузера (а не в отдельном) запусти `start_browser.bat` из корня
проекта — подробности в [README корня проекта](../README.md).
