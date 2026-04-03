"""Clipboard helpers with history."""

from __future__ import annotations

import pyperclip

from daia.memory import MemoryStore


class ClipboardManager:
    """Read, write, and track clipboard content."""

    def __init__(self, memory: MemoryStore, limit: int = 20) -> None:
        self.memory = memory
        self.limit = limit

    def read(self) -> str:
        """Return current clipboard content."""

        return pyperclip.paste()

    def write(self, content: str) -> None:
        """Write content to the clipboard and history."""

        pyperclip.copy(content)
        self.memory.add_clipboard_entry(content, limit=self.limit)

    def history(self) -> list[dict[str, str | int]]:
        """Return clipboard history."""

        return [dict(row) for row in self.memory.clipboard_history(limit=self.limit)]

    def paste_history_item(self, index: int) -> str:
        """Copy a historical clipboard item back into the clipboard."""

        history = self.memory.clipboard_history(limit=self.limit)
        if index < 0 or index >= len(history):
            raise IndexError("Clipboard history index out of range.")
        content = history[index]["content"]
        pyperclip.copy(content)
        return str(content)
