"""Browser automation and Google Docs workflows."""

from __future__ import annotations

import platform
import subprocess
import time
import webbrowser
from dataclasses import dataclass
from typing import Any

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

    def google_docs_create_and_type(
        self,
        content: str,
        typing_simulator: TypingSimulator,
        headless: bool = False,
        browser_mode: str = "default",
    ) -> dict[str, Any]:
        """Open Google Docs, create a document, and type the content."""

        if browser_mode == "default":
            self.open_default("https://docs.new")
            time.sleep(5)
            self._focus_frontmost_browser()
            time.sleep(2)
            stats = typing_simulator.type_text(content)
            word_count = len(content.split())
            return {"word_count": word_count, "url": "https://docs.new", "typing_stats": stats}

        session = self.start_headless(headless=headless)
        page = session.page
        page.goto("https://docs.new", wait_until="load")
        try:
            page.wait_for_load_state("networkidle", timeout=30000)
        except TimeoutError:
            pass
        time.sleep(2)
        page.bring_to_front()
        stats = typing_simulator.type_text(content)
        page.keyboard.press("MetaOrControl+S")
        word_count = len(content.split())
        return {"word_count": word_count, "url": page.url, "typing_stats": stats}
