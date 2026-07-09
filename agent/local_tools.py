"""
Client-side tool schemas for tools that don't go through the MCP server.
These are passed manually to the Anthropic API as part of the tools list.
"""

FINISH_TOOL_SCHEMA: dict = {
    "name": "finish",
    "description": (
        "Вызови этот инструмент когда задача пользователя полностью выполнена. "
        "Передай краткое описание того, что было сделано и каков итоговый результат. "
        "Устанавливай success=false если задача не могла быть выполнена."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "result": {
                "type": "string",
                "description": "Краткое описание итога выполненной задачи",
            },
            "success": {
                "type": "boolean",
                "description": "true — задача выполнена успешно, false — не удалось выполнить",
            },
        },
        "required": ["result", "success"],
    },
}

CONFIRM_ACTION_TOOL_SCHEMA: dict = {
    "name": "confirm_action",
    "description": (
        "Вызови этот инструмент ПЕРЕД важным или необратимым действием, чтобы получить "
        "подтверждение пользователя: оплата, оформление/подтверждение заказа, отправка "
        "формы с личными данными, удаление чего-либо, отправка сообщений от имени "
        "пользователя. Опиши, что именно собираешься сделать, со всеми важными деталями "
        "(товар, цена, адрес, получатель). Выполняй действие только после явного "
        "согласия пользователя; при отказе — не выполняй и уточни, что делать дальше."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action_description": {
                "type": "string",
                "description": (
                    "Что именно будет сделано и его ключевые детали, "
                    "например: 'Оплатить заказ №123 на сумму 4 990 ₽ картой *4242'"
                ),
            },
        },
        "required": ["action_description"],
    },
}

ASK_USER_TOOL_SCHEMA: dict = {
    "name": "ask_user",
    "description": (
        "Вызови этот инструмент только когда для продолжения работы нужна информация, "
        "которую невозможно получить самостоятельно из браузера: логин, пароль, "
        "выбор между несколькими равнозначными вариантами и т.п. "
        "Не используй этот инструмент без крайней необходимости."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "Конкретный вопрос пользователю",
            },
        },
        "required": ["question"],
    },
}
