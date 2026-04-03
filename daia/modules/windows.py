"""Cross-platform window management."""

from __future__ import annotations

import platform
import subprocess
from typing import Any

import pygetwindow as gw


class WindowManager:
    """Lists and controls windows where platform support exists."""

    def list_windows(self) -> list[dict[str, Any]]:
        """List open windows."""

        system = platform.system()
        if system == "Darwin":
            return self._list_windows_macos()
        windows = []
        if hasattr(gw, "getAllWindows"):
            for win in gw.getAllWindows():
                title = getattr(win, "title", "")
                if not title:
                    continue
                windows.append(
                    {
                        "title": title,
                        "left": getattr(win, "left", 0),
                        "top": getattr(win, "top", 0),
                        "width": getattr(win, "width", 0),
                        "height": getattr(win, "height", 0),
                    }
                )
        return windows

    def _find_window(self, title_substring: str):
        system = platform.system()
        if system == "Darwin":
            for win in self._list_windows_macos():
                if title_substring.lower() in win["title"].lower():
                    return win
            raise ValueError(f"No window found containing '{title_substring}'.")
        needle = title_substring.lower()
        for win in gw.getAllWindows():
            title = getattr(win, "title", "")
            if needle in title.lower():
                return win
        raise ValueError(f"No window found containing '{title_substring}'.")

    def focus(self, title_substring: str) -> None:
        """Focus a window by title substring."""

        if platform.system() == "Darwin":
            self._osascript(
                f'''
                tell application "System Events"
                    repeat with proc in application processes
                        if background only of proc is false then
                            repeat with win in windows of proc
                                if (name of win as text) contains "{self._escape(title_substring)}" then
                                    set frontmost of proc to true
                                    perform action "AXRaise" of win
                                    return
                                end if
                            end repeat
                        end if
                    end repeat
                end tell
                '''
            )
            return
        window = self._find_window(title_substring)
        window.activate()

    def move_resize(self, title_substring: str, x: int, y: int, width: int, height: int) -> None:
        """Move and resize a window."""

        if platform.system() == "Darwin":
            self._osascript(
                f'''
                tell application "System Events"
                    repeat with proc in application processes
                        repeat with win in windows of proc
                            if (name of win as text) contains "{self._escape(title_substring)}" then
                                set position of win to {{{x}, {y}}}
                                set size of win to {{{width}, {height}}}
                                return
                            end if
                        end repeat
                    end repeat
                end tell
                '''
            )
            return
        window = self._find_window(title_substring)
        window.moveTo(x, y)
        window.resizeTo(width, height)

    def minimize(self, title_substring: str) -> None:
        if platform.system() == "Darwin":
            self._osascript(
                f'''
                tell application "System Events"
                    repeat with proc in application processes
                        repeat with win in windows of proc
                            if (name of win as text) contains "{self._escape(title_substring)}" then
                                set value of attribute "AXMinimized" of win to true
                                return
                            end if
                        end repeat
                    end repeat
                end tell
                '''
            )
            return
        self._find_window(title_substring).minimize()

    def maximize(self, title_substring: str) -> None:
        if platform.system() == "Darwin":
            self._osascript(
                f'''
                tell application "System Events"
                    repeat with proc in application processes
                        repeat with win in windows of proc
                            if (name of win as text) contains "{self._escape(title_substring)}" then
                                set value of attribute "AXFullScreen" of win to true
                                return
                            end if
                        end repeat
                    end repeat
                end tell
                '''
            )
            return
        self._find_window(title_substring).maximize()

    def close(self, title_substring: str) -> None:
        if platform.system() == "Darwin":
            self._osascript(
                f'''
                tell application "System Events"
                    repeat with proc in application processes
                        repeat with win in windows of proc
                            if (name of win as text) contains "{self._escape(title_substring)}" then
                                perform action "AXClose" of win
                                return
                            end if
                        end repeat
                    end repeat
                end tell
                '''
            )
            return
        self._find_window(title_substring).close()

    def focused_window(self) -> str:
        """Return the active window title."""

        system = platform.system()
        if system == "Darwin":
            script = (
                'tell application "System Events" to get name of first application process whose frontmost is true'
            )
            result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, check=False)
            return result.stdout.strip() or "Unknown"
        if system == "Linux":
            result = subprocess.run(["xdotool", "getactivewindow", "getwindowname"], capture_output=True, text=True, check=False)
            return result.stdout.strip() or "Unknown"
        active = gw.getActiveWindow()
        return getattr(active, "title", "Unknown")

    def _list_windows_macos(self) -> list[dict[str, Any]]:
        script = r'''
        tell application "System Events"
            set output_lines to {}
            repeat with proc in (application processes where background only is false)
                try
                    repeat with win in windows of proc
                        set end of output_lines to ((name of proc as text) & "||" & (name of win as text))
                    end repeat
                end try
            end repeat
            set AppleScript's text item delimiters to linefeed
            return output_lines as text
        end tell
        '''
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, check=False)
        if result.returncode != 0:
            return []
        entries: list[dict[str, Any]] = []
        raw = result.stdout.strip()
        if not raw:
            return entries
        for item in raw.splitlines():
            if "||" not in item:
                continue
            app_name, title = item.split("||", 1)
            entries.append(
                {
                    "title": title or app_name,
                    "app": app_name,
                    "left": 0,
                    "top": 0,
                    "width": 0,
                    "height": 0,
                }
            )
        return entries

    @staticmethod
    def _osascript(script: str) -> None:
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "AppleScript window command failed.")

    @staticmethod
    def _escape(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')
