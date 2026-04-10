"""Browser automation and Google Docs workflows."""

from __future__ import annotations

import platform
import subprocess
import time
import webbrowser
from dataclasses import dataclass
from typing import Any, Callable

from playwright.sync_api import Browser, Page, Playwright, TimeoutError, sync_playwright

from daia.modules.typing_sim import TypingSimulator


@dataclass(slots=True)
class BrowserSession:
    """Holds Playwright objects."""

    playwright: Playwright
    browser: Browser
    page: Page


class BrowserController:
    """Supports default browser and Playwright automation."""

    def __init__(self) -> None:
        self.session: BrowserSession | None = None

    def open_default(self, url: str) -> None:
        webbrowser.open(url, new=2, autoraise=True)

    @staticmethod
    def _primary_modifier() -> str:
        return "command" if platform.system() == "Darwin" else "ctrl"

    @staticmethod
    def _focus_frontmost_browser() -> None:
        """Best-effort focus handoff to the default browser on macOS."""

        if platform.system() != "Darwin":
            return
        script = """
        tell application "System Events"
            set frontApp to name of first application process whose frontmost is true
        end tell
        tell application frontApp to activate
        """
        try:
            subprocess.run(["osascript", "-e", script], check=False, capture_output=True)
        except Exception:
            return

    @staticmethod
    def _send_hotkey(*keys: str) -> None:
        import pyautogui

        pyautogui.hotkey(*keys)

    def _focus_browser_input(self) -> None:
        """Focus a reliable browser text target."""

        self._send_hotkey(self._primary_modifier(), "l")
        time.sleep(0.2)

    @staticmethod
    def _press_enter() -> None:
        import pyautogui

        pyautogui.press("enter")

    @staticmethod
    def _press_key(key: str) -> None:
        import pyautogui

        pyautogui.press(key)

    @staticmethod
    def _click_relative(x_ratio: float, y_ratio: float) -> None:
        import pyautogui

        width, height = pyautogui.size()
        x = int(width * x_ratio)
        y = int(height * y_ratio)
        pyautogui.moveTo(x, y, duration=0.25)
        pyautogui.click()

    def _focus_google_docs_canvas(self) -> None:
        """Best-effort focus on the editable Google Docs canvas."""

        self._focus_frontmost_browser()
        time.sleep(0.5)
        self._press_key("esc")
        time.sleep(0.2)
        # Docs places the editable canvas near the visual center of the page.
        self._click_relative(0.52, 0.46)
        time.sleep(0.35)
        self._click_relative(0.52, 0.46)
        time.sleep(0.35)

    def start_headless(self, headless: bool = True) -> BrowserSession:
        """Start or reuse a Playwright browser session."""

        if self.session is not None:
            return self.session
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(headless=headless)
        page = browser.new_page()
        self.session = BrowserSession(playwright=playwright, browser=browser, page=page)
        return self.session

    def close(self) -> None:
        """Close Playwright session."""

        if self.session is None:
            return
        self.session.browser.close()
        self.session.playwright.stop()
        self.session = None

    def open_url(self, url: str, headless: bool = True) -> str:
        """Open a URL in Playwright."""

        session = self.start_headless(headless=headless)
        session.page.goto(url, wait_until="domcontentloaded")
        return session.page.url

    def fill_field(self, label_or_placeholder: str, value: str) -> None:
        """Fill an input by label or placeholder."""

        if self.session is None:
            raise RuntimeError("Headless browser session is not running.")
        page = self.session.page
        locator = page.get_by_label(label_or_placeholder)
        if locator.count() == 0:
            locator = page.get_by_placeholder(label_or_placeholder)
        locator.first.fill(value)

    def click_text(self, text: str) -> None:
        """Click a button or link by visible text."""

        if self.session is None:
            raise RuntimeError("Headless browser session is not running.")
        page = self.session.page
        try:
            page.get_by_role("button", name=text).first.click()
            return
        except Exception:
            pass
        try:
            page.get_by_role("link", name=text).first.click()
            return
        except Exception:
            pass
        page.get_by_text(text).first.click()

    def extract_text(self) -> str:
        """Return page text content."""

        if self.session is None:
            raise RuntimeError("Headless browser session is not running.")
        return self.session.page.locator("body").inner_text()

    def google_search(
        self,
        query: str,
        typing_simulator: TypingSimulator,
        paste_fallback: Callable[[str], dict[str, int | float]] | None = None,
        *,
        headless: bool = False,
        browser_mode: str = "default",
    ) -> dict[str, Any]:
        """Open Google and submit a query through a visible browser input."""

        clean_query = query.strip()
        if not clean_query:
            raise ValueError("Google search query cannot be empty.")

        if browser_mode == "default":
            self.open_default("https://www.google.com")
            time.sleep(3.0)
            self._focus_frontmost_browser()
            time.sleep(0.6)
            self._focus_browser_input()
            try:
                stats = typing_simulator.type_text(clean_query)
                input_mode = "typed"
            except Exception:
                if paste_fallback is None:
                    raise
                stats = paste_fallback(clean_query)
                input_mode = "pasted"
            time.sleep(0.15)
            self._press_enter()
            return {
                "query": clean_query,
                "url": f"https://www.google.com/search?q={clean_query}",
                "input_mode": input_mode,
                "typing_stats": stats,
            }

        session = self.start_headless(headless=headless)
        page = session.page
        page.goto("https://www.google.com", wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except TimeoutError:
            pass
        try:
            page.get_by_role("button", name="Accept all").first.click(timeout=2000)
        except Exception:
            pass
        try:
            page.locator('textarea[name="q"]').first.wait_for(timeout=10000)
            page.locator('textarea[name="q"]').first.fill(clean_query)
        except Exception:
            page.keyboard.press(f"{'Meta' if platform.system() == 'Darwin' else 'Control'}+L")
            page.keyboard.type(clean_query)
        page.keyboard.press("Enter")
        return {
            "query": clean_query,
            "url": page.url,
            "input_mode": "typed",
            "typing_stats": {"typed_chars": len(clean_query), "corrections": 0, "elapsed": 0.0},
        }

    def google_docs_create_and_type(
        self,
        content: str,
        typing_simulator: TypingSimulator,
        paste_fallback: Callable[[str], dict[str, int | float]] | None = None,
        headless: bool = False,
        browser_mode: str = "default",
    ) -> dict[str, Any]:
        """Open Google Docs, create a document, and type the content."""

        if browser_mode == "default":
            self.open_default("https://docs.new")
            time.sleep(7)
            self._focus_google_docs_canvas()
            try:
                stats = typing_simulator.type_text(content)
                input_mode = "typed"
            except Exception:
                if paste_fallback is None:
                    raise
                stats = paste_fallback(content)
                input_mode = "pasted"
            word_count = len(content.split())
            return {
                "word_count": word_count,
                "url": "https://docs.new",
                "typing_stats": stats,
                "input_mode": input_mode,
            }

        session = self.start_headless(headless=headless)
        page = session.page
        page.goto("https://docs.new", wait_until="load")
        try:
            page.wait_for_load_state("networkidle", timeout=30000)
        except TimeoutError:
            pass
        time.sleep(2)
        page.bring_to_front()
        try:
            page.mouse.click(page.viewport_size["width"] // 2, page.viewport_size["height"] // 2)
        except Exception:
            pass
        stats = typing_simulator.type_text(content)
        page.keyboard.press("MetaOrControl+S")
        word_count = len(content.split())
        return {
            "word_count": word_count,
            "url": page.url,
            "typing_stats": stats,
            "input_mode": "typed",
        }
