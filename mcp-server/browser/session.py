from __future__ import annotations

import os
from pathlib import Path

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    Playwright,
    ElementHandle,
    Dialog,
)

# CDP endpoint of the user's own browser (started with --remote-debugging-port).
# When reachable, the agent attaches to it and acts in the user's current window
# instead of opening a separate one. See start_browser.bat.
CDP_URL = os.environ.get("BROWSER_CDP_URL", "http://127.0.0.1:9222")
HEADLESS = os.environ.get("HEADLESS", "false").lower() == "true"

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_EXTENSION_DIR = _PROJECT_ROOT / "extension"
# Fallback browser keeps its profile (logins, cookies) between runs.
_PROFILE_DIR = _PROJECT_ROOT / "mcp-server" / ".browser-profile"

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
        self._browser: Browser | None = None  # set only when attached over CDP
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._element_handles: list[ElementHandle] = []
        self._pending_dialog: Dialog | None = None

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def _reset(self, *_: object) -> None:
        self._browser = None
        self._context = None
        self._page = None
        self._element_handles = []

    async def _ensure_started(self) -> None:
        # Guard on the final artifact (_page), not the first step (_playwright):
        # a failed launch must not leave the session stuck half-initialized,
        # and a page/browser closed by the user must be recreated.
        if self._page is not None and not self._page.is_closed():
            return
        if self._playwright is None:
            self._playwright = await async_playwright().start()
        try:
            if self._context is None:
                await self._open_context()
            self._page = await self._pick_page()
            self._page.on("dialog", self._on_dialog)
            self._element_handles = []
        except Exception:
            self._reset()
            raise

    async def _open_context(self) -> None:
        # In headless mode (Docker), skip CDP and launch headless Chromium.
        if HEADLESS:
            self._context = await self._playwright.chromium.launch_persistent_context(
                str(_PROFILE_DIR),
                headless=True,
                no_viewport=True,
            )
            self._context.on("close", self._reset)
            return

        # 1) Preferred: attach to the user's running browser over CDP —
        #    actions happen in the window the user is already looking at.
        try:
            self._browser = await self._playwright.chromium.connect_over_cdp(
                CDP_URL, timeout=1_500
            )
            contexts = self._browser.contexts
            self._context = contexts[0] if contexts else await self._browser.new_context()
            self._browser.on("disconnected", self._reset)
            return
        except Exception:
            self._browser = None

        # 2) Fallback: own Chromium window with the extension pre-loaded,
        #    so agent actions and the extension UI still share one window.
        self._context = await self._playwright.chromium.launch_persistent_context(
            str(_PROFILE_DIR),
            headless=False,
            no_viewport=True,
            args=[
                f"--disable-extensions-except={_EXTENSION_DIR}",
                f"--load-extension={_EXTENSION_DIR}",
            ],
        )
        self._context.on("close", self._reset)

    async def _pick_page(self) -> Page:
        """Prefer the tab the user is currently looking at; else reuse/create one."""
        # Extension popups (chrome-extension://) and browser-internal pages also
        # live in the context and report visibilityState=visible — skip them.
        pages = [
            p
            for p in self._context.pages
            if p.url.startswith(("http://", "https://", "about:"))
        ]
        for page in pages:
            try:
                if await page.evaluate("document.visibilityState") == "visible":
                    return page
            except Exception:
                continue
        if pages:
            return pages[-1]
        return await self._context.new_page()

    def _on_dialog(self, dialog: Dialog) -> None:
        # Sync handler: Playwright doesn't await async handlers before auto-dismissing.
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
