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
