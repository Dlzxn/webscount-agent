from __future__ import annotations

import asyncio
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

# Hard cap on interactive elements per snapshot — huge pages (marketplaces,
# infinite feeds) otherwise blow up both latency and the LLM context.
MAX_ELEMENTS = 300

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
    """
    Wrapper around one Playwright browser context with focus-follows-new-tab
    semantics: a tab/popup opened by any click becomes the active page (as it
    does for a real user), and if the active tab is closed, focus falls back
    to the most recent still-open one. All tools act on `active_page`.
    """

    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None  # set only when attached over CDP
        self._context: BrowserContext | None = None
        self._active_page: Page | None = None
        self._snapshot_page: Page | None = None  # page shown in the previous snapshot
        self._wired_pages: set[Page] = set()  # pages with our event handlers attached
        self._element_handles: list[ElementHandle] = []
        self._pending_dialog: Dialog | None = None
        self._downloads: list[str] = []  # filenames of downloads not yet reported

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def _reset(self, *_: object) -> None:
        self._browser = None
        self._context = None
        self._active_page = None
        self._snapshot_page = None
        self._wired_pages = set()
        self._element_handles = []
        self._downloads = []

    @property
    def active_page(self) -> Page | None:
        """
        The tab all tools act on. If the remembered active tab was closed
        (by the agent, the site, or the user), lazily falls back to the most
        recent page that is still open.
        """
        if self._active_page is not None and not self._active_page.is_closed():
            return self._active_page
        pages = self._pages()
        if pages:
            self._activate(pages[-1])
            return self._active_page
        return None

    def _pages(self) -> list[Page]:
        """Open pages of the context, excluding extension/browser-internal ones."""
        if self._context is None:
            return []
        return [
            p
            for p in self._context.pages
            if not p.is_closed()
            and p.url.startswith(("http://", "https://", "about:"))
        ]

    def _activate(self, page: Page) -> None:
        if page is self._active_page:
            return
        self._active_page = page
        # Element numbers from the previous snapshot belong to another tab —
        # a stale click must fail with "call read_page", not hit the old tab.
        self._element_handles = []

    def _wire_page(self, page: Page) -> None:
        if page in self._wired_pages:
            return
        self._wired_pages.add(page)
        page.on("dialog", self._on_dialog)
        page.on("close", self._on_page_close)
        page.on("download", self._on_download)

    def _on_new_page(self, page: Page) -> None:
        # context "page" event: fires for ANY new tab or popup in the context.
        # Sync handler on purpose — the page may close before it ever finishes
        # loading (short-lived ad popups), so nothing is awaited here; waiting
        # happens later in _settle(), and active_page tolerates a closed page.
        self._wire_page(page)
        self._activate(page)

    def _on_page_close(self, page: Page) -> None:
        self._wired_pages.discard(page)
        if page is self._active_page:
            self._active_page = None  # active_page property falls back lazily

    async def _ensure_started(self) -> None:
        # Guard on the final artifact (a live active page), not the first step:
        # a failed launch must not leave the session stuck half-initialized,
        # and a page/browser closed by the user must be recreated.
        if self._context is not None and self.active_page is not None:
            return
        if self._playwright is None:
            self._playwright = await async_playwright().start()
        try:
            if self._context is None:
                await self._open_context()
                # Single subscription point for new tabs/popups in this context.
                self._context.on("page", self._on_new_page)
            page = await self._pick_page()
            self._wire_page(page)
            self._activate(page)
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
        pages = self._pages()
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

    def _on_download(self, download: object) -> None:
        # Report-only: the browser saves the file per its own settings; the
        # agent just needs to know a download happened instead of silence.
        try:
            self._downloads.append(download.suggested_filename)
        except Exception:
            self._downloads.append("(неизвестный файл)")

    # ── Internal helpers ─────────────────────────────────────────────────────

    async def _grace_for_popup(self) -> None:
        """
        The context "page" event for a click-spawned tab/popup arrives over
        the protocol slightly AFTER click() returns (~100–200ms). Give it a
        short window so the snapshot below already shows the new tab. If a
        popup is slower than this, nothing is lost: the switch still happens
        via the event, and _tab_change_notice reports it on the next call.
        """
        before = self._active_page
        for _ in range(4):
            await asyncio.sleep(0.1)
            if self._active_page is not before:
                return

    async def _settle(self) -> None:
        """Wait for the active page's DOM after navigation / interaction."""
        page = self.active_page
        if page is None:
            return
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=15_000)
        except Exception:
            # Slow page or a popup that closed mid-wait — not fatal either way.
            pass
        try:
            # Bounded wait for XHR-driven updates (search results, dynamic
            # widgets). SPAs that never go idle just hit the cap and move on.
            await page.wait_for_load_state("networkidle", timeout=2_500)
        except Exception:
            pass

    def _tab_change_notice(self, page: Page) -> str | None:
        """
        One-shot warning for the LLM: returned only on the first snapshot after
        the shown tab actually changed (new tab opened, active tab closed, or
        explicit switch_tab) — never repeated on subsequent calls.
        """
        prev, self._snapshot_page = self._snapshot_page, page
        if prev is None or page is prev:
            return None
        return (
            f"⚠️ Активная вкладка сменилась (url: {page.url}, "
            f"всего открытых вкладок: {len(self._pages())}). "
            "Ниже — содержимое новой активной вкладки; номера элементов из "
            "прошлых snapshot недействительны. Список вкладок — list_tabs, "
            "вернуться на другую вкладку — switch_tab."
        )

    async def _query_tree(self) -> list[dict]:
        """
        Query all currently visible interactive elements and headings of the
        active page, including elements inside iframes (payment forms, embedded
        widgets). Stores handles for later click/fill/select — a handle stays
        bound to its frame, so interaction works transparently.
        Returns a flat list that build_snapshot can format.
        """
        page = self.active_page
        if page is None:
            return []

        handles: list[ElementHandle] = []
        elements: list[dict] = []
        for frame in page.frames:
            if frame.is_detached() or len(handles) >= MAX_ELEMENTS:
                continue
            in_iframe = frame is not page.main_frame
            try:
                found = await frame.query_selector_all(_INTERACTIVE)
            except Exception:
                continue  # frame died mid-query — skip it
            for el in found:
                if len(handles) >= MAX_ELEMENTS:
                    break
                try:
                    # Skip CSS-hidden elements (display:none, zero-size, etc.)
                    if not await el.is_visible():
                        continue
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

                    handles.append(el)
                    elements.append({
                        "id": len(handles),
                        "kind": "interactive",
                        "tag": tag,
                        "role": role,
                        "label": label,
                        "input_type": input_type,
                        "value": value[:80],
                        "iframe": in_iframe,
                    })
                except Exception:
                    # Element became stale or detached — skip it.
                    continue
        self._element_handles = handles

        # Headings give the LLM navigation context without an interactive ID.
        headings: list[dict] = []
        try:
            heading_els = await page.query_selector_all("h1, h2, h3")
        except Exception:
            heading_els = []
        for el in heading_els:
            try:
                text = ((await el.text_content()) or "").strip()[:150]
                if text:
                    headings.append({"kind": "heading", "label": text})
            except Exception:
                continue

        tree = headings + elements
        for name in self._downloads:
            tree = [{
                "kind": "notice",
                "label": f"📥 Браузер начал скачивание файла: {name}",
            }] + tree
        self._downloads = []
        notice = self._tab_change_notice(page)
        if notice:
            tree = [{"kind": "notice", "label": notice}] + tree
        return tree

    def _handle_or_raise(self, element_id: int) -> ElementHandle:
        n = len(self._element_handles)
        if element_id < 1 or element_id > n:
            raise ValueError(
                f"Элемент #{element_id} не найден. "
                f"Доступны номера 1–{n}. "
                "Сначала вызови read_page чтобы получить актуальный список."
            )
        return self._element_handles[element_id - 1]

    # ── Public API (called by tools/) ────────────────────────────────────────

    async def get_accessibility_tree(self) -> list[dict]:
        await self._ensure_started()
        return await self._query_tree()

    async def goto(self, url: str) -> list[dict]:
        await self._ensure_started()
        await self.active_page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        await self._settle()
        return await self._query_tree()

    async def go_back(self) -> list[dict]:
        await self._ensure_started()
        await self.active_page.go_back(wait_until="domcontentloaded", timeout=15_000)
        await self._settle()
        return await self._query_tree()

    async def scroll(self, direction: str, amount: str) -> list[dict]:
        await self._ensure_started()
        page = self.active_page
        if amount == "bottom":
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        elif direction == "down":
            await page.evaluate("window.scrollBy(0, window.innerHeight)")
        else:
            await page.evaluate("window.scrollBy(0, -window.innerHeight)")
        await page.wait_for_timeout(600)
        return await self._query_tree()

    async def click_element(self, element_id: int) -> list[dict]:
        # If the click spawns a new tab, _on_new_page switches active_page to
        # it during _grace_for_popup, so the snapshot below shows the new tab.
        await self._handle_or_raise(element_id).click(timeout=10_000)
        await self._grace_for_popup()
        await self._settle()
        return await self._query_tree()

    async def fill_element(self, element_id: int, text: str) -> list[dict]:
        el = self._handle_or_raise(element_id)
        await el.click(timeout=5_000)
        await el.fill(text, timeout=5_000)
        return await self._query_tree()

    async def select_option_element(self, element_id: int, option_label: str) -> list[dict]:
        await self._handle_or_raise(element_id).select_option(
            label=option_label, timeout=5_000
        )
        return await self._query_tree()

    async def press_key(self, key: str) -> list[dict]:
        await self._ensure_started()
        page = self.active_page
        await page.keyboard.press(key)
        await page.wait_for_timeout(500)
        await self._settle()
        return await self._query_tree()

    async def get_full_text(self, max_chars: int = 5000) -> str:
        await self._ensure_started()
        page = self.active_page
        text = await page.inner_text("body")
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n\n... (обрезано, всего {len(text)} символов)"
        notice = self._tab_change_notice(page)
        return f"{notice}\n\n{text}" if notice else text

    async def screenshot(self) -> bytes:
        """JPEG of the visible viewport of the active tab."""
        await self._ensure_started()
        return await self.active_page.screenshot(type="jpeg", quality=55)

    async def get_state(self) -> dict:
        await self._ensure_started()
        page = self.active_page
        state: dict = {
            "url": page.url,
            "title": await page.title(),
            "tabs_open": len(self._pages()),
        }
        notice = self._tab_change_notice(page)
        if notice:
            state["notice"] = notice
        return state

    async def list_tabs(self) -> list[dict]:
        await self._ensure_started()
        active = self.active_page
        tabs: list[dict] = []
        for i, page in enumerate(self._pages(), start=1):
            try:
                title = await page.title()
            except Exception:
                title = ""
            tabs.append({
                "index": i,
                "url": page.url,
                "title": title,
                "active": page is active,
            })
        return tabs

    async def switch_tab(self, index: int) -> list[dict]:
        await self._ensure_started()
        pages = self._pages()
        if index < 1 or index > len(pages):
            raise ValueError(
                f"Вкладка #{index} не найдена. Доступны номера 1–{len(pages)}. "
                "Сначала вызови list_tabs чтобы получить актуальный список."
            )
        page = pages[index - 1]
        self._wire_page(page)
        self._activate(page)
        try:
            await page.bring_to_front()
        except Exception:
            pass  # focus in the real window is best-effort; наша ссылка уже переключена
        return await self._query_tree()

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
