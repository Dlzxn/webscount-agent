from __future__ import annotations

from playwright.async_api import (
    async_playwright,
    Browser,
    Page,
    Playwright,
    ElementHandle,
    Dialog,
)

# Selects every element that a user can interact with.
_INTERACTIVE = (
    "a[href], "
    "button:not([disabled]), "
    "input:not([type='hidden']):not([disabled]), "
    "select:not([disabled]), "
    "textarea:not([disabled]), "
    "[role='button']:not([disabled]), "
    "[role='link'], "
    "[role='checkbox'], "
    "[role='radio'], "
    "[role='tab'], "
    "[role='menuitem'], "
    "[role='combobox']:not([disabled])"
)


class BrowserSession:
    """Thin wrapper around a single Playwright page."""

    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._page: Page | None = None
        self._element_handles: list[ElementHandle] = []
        self._pending_dialog: Dialog | None = None

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def _ensure_started(self) -> None:
        if self._playwright is not None:
            return
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=False)
        self._page = await self._browser.new_page()
        self._page.on("dialog", self._on_dialog)

    async def _on_dialog(self, dialog: Dialog) -> None:
        self._pending_dialog = dialog

    # ── Internal helpers ─────────────────────────────────────────────────────

    async def _settle(self) -> None:
        """Wait for DOM to be ready after navigation / interaction."""
        try:
            await self._page.wait_for_load_state("domcontentloaded", timeout=15_000)
        except Exception:
            pass

    async def _query_tree(self) -> list[dict]:
        """
        Query all currently visible interactive elements and headings.
        Stores handles for later click/fill/select operations.
        Returns a flat list that build_snapshot can format.
        """
        page = self._page

        interactive = await page.query_selector_all(_INTERACTIVE)
        self._element_handles = interactive

        elements: list[dict] = []
        idx = 1
        for el in interactive:
            try:
                tag: str = await el.evaluate("el => el.tagName.toLowerCase()")
                role: str = await el.get_attribute("role") or tag
                aria_label: str = await el.get_attribute("aria-label") or ""
                placeholder: str = await el.get_attribute("placeholder") or ""
                input_type: str = await el.get_attribute("type") or ""
                text: str = ((await el.text_content()) or "").strip()
                value: str = (await el.evaluate(
                    "el => ('value' in el ? el.value : '')"
                ) or "").strip()

                label = (aria_label or text or placeholder or value or input_type or tag)[:120]

                elements.append({
                    "id": idx,
                    "kind": "interactive",
                    "tag": tag,
                    "role": role,
                    "label": label,
                    "input_type": input_type,
                    "value": value[:80],
                })
                idx += 1
            except Exception:
                # Element became stale or detached — skip it.
                self._element_handles[idx - 1 : idx] = []
                continue

        # Headings give the LLM navigation context without an interactive ID.
        headings: list[dict] = []
        for el in await page.query_selector_all("h1, h2, h3"):
            try:
                text = ((await el.text_content()) or "").strip()[:150]
                if text:
                    headings.append({"kind": "heading", "label": text})
            except Exception:
                continue

        return headings + elements

    # ── Public API (called by tools/) ────────────────────────────────────────

    async def get_accessibility_tree(self) -> list[dict]:
        await self._ensure_started()
        return await self._query_tree()

    async def goto(self, url: str) -> list[dict]:
        await self._ensure_started()
        await self._page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        return await self._query_tree()

    async def go_back(self) -> list[dict]:
        await self._ensure_started()
        await self._page.go_back(wait_until="domcontentloaded", timeout=15_000)
        return await self._query_tree()

    async def scroll(self, direction: str, amount: str) -> list[dict]:
        await self._ensure_started()
        if amount == "bottom":
            await self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        elif direction == "down":
            await self._page.evaluate("window.scrollBy(0, window.innerHeight)")
        else:
            await self._page.evaluate("window.scrollBy(0, -window.innerHeight)")
        await self._page.wait_for_timeout(600)
        return await self._query_tree()

    async def click_element(self, element_id: int) -> list[dict]:
        n = len(self._element_handles)
        if element_id < 1 or element_id > n:
            raise ValueError(
                f"Элемент #{element_id} не найден. "
                f"Доступны номера 1–{n}. "
                "Сначала вызови read_page чтобы получить актуальный список."
            )
        await self._element_handles[element_id - 1].click(timeout=10_000)
        await self._settle()
        return await self._query_tree()

    async def fill_element(self, element_id: int, text: str) -> list[dict]:
        n = len(self._element_handles)
        if element_id < 1 or element_id > n:
            raise ValueError(
                f"Элемент #{element_id} не найден. "
                f"Доступны номера 1–{n}. Сначала вызови read_page."
            )
        el = self._element_handles[element_id - 1]
        await el.click(timeout=5_000)
        await el.fill(text, timeout=5_000)
        return await self._query_tree()

    async def select_option_element(self, element_id: int, option_label: str) -> list[dict]:
        n = len(self._element_handles)
        if element_id < 1 or element_id > n:
            raise ValueError(
                f"Элемент #{element_id} не найден. "
                f"Доступны номера 1–{n}. Сначала вызови read_page."
            )
        await self._element_handles[element_id - 1].select_option(
            label=option_label, timeout=5_000
        )
        return await self._query_tree()

    async def press_key(self, key: str) -> list[dict]:
        await self._ensure_started()
        await self._page.keyboard.press(key)
        await self._page.wait_for_timeout(500)
        await self._settle()
        return await self._query_tree()

    async def get_full_text(self) -> str:
        await self._ensure_started()
        return await self._page.inner_text("body")

    async def get_url(self) -> str:
        await self._ensure_started()
        return self._page.url

    async def get_title(self) -> str:
        await self._ensure_started()
        return await self._page.title()

    async def handle_dialog(self, action: str) -> str:
        if self._pending_dialog is None:
            return "Нет активного диалога для обработки."
        dialog = self._pending_dialog
        self._pending_dialog = None
        if action == "accept":
            await dialog.accept()
            return f"Диалог ({dialog.type}) принят."
        else:
            await dialog.dismiss()
            return f"Диалог ({dialog.type}) отклонён."
