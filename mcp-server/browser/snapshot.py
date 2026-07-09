"""
Converts the raw element list returned by BrowserSession._query_tree()
into a compact, numbered text representation for the LLM.
"""

_TAG_KIND: dict[str, str] = {
    "a": "link",
    "button": "button",
    "textarea": "textarea",
    "select": "select",
}


def _element_kind(el: dict) -> str:
    tag = el.get("tag", "")
    role = el.get("role", "")
    input_type = el.get("input_type", "")

    if tag == "input":
        return f"input[{input_type}]" if input_type else "input"
    if role in {"button", "link", "checkbox", "radio", "tab", "menuitem", "combobox"}:
        return role
    return _TAG_KIND.get(tag, role or tag or "element")


def build_snapshot(raw_tree: list[dict]) -> str:
    """
    raw_tree — list returned by BrowserSession.get_accessibility_tree().
    Each item is either {"kind": "heading", "label": str}
    or {"kind": "interactive", "id": int, ...}.

    Returns a human-readable numbered snapshot string.
    """
    if not raw_tree:
        return "(Страница пуста или недоступна)"

    headings = [el for el in raw_tree if el.get("kind") == "heading"]
    interactive = [el for el in raw_tree if el.get("kind") == "interactive"]

    lines: list[str] = []

    if headings:
        for h in headings:
            lines.append(f"# {h['label']}")
        lines.append("")

    if not interactive:
        lines.append("(Нет интерактивных элементов)")
    else:
        for el in interactive:
            idx = el["id"]
            kind = _element_kind(el)
            label = el.get("label", "")
            value = el.get("value", "")

            line = f"[{idx}] {kind}: {label}"
            if value:
                line += f'  (текущее значение: "{value}")'
            lines.append(line)

    return "\n".join(lines)
