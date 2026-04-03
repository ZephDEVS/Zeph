"""Activity logging utilities."""

from __future__ import annotations

import logging
from pathlib import Path

from daia.config import LOG_PATH


class ActivityLogger:
    """Structured logger for Zeph activity."""

    def __init__(self, path: Path = LOG_PATH) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger("daia")
        if not self.logger.handlers:
            self.logger.setLevel(logging.INFO)
            handler = logging.FileHandler(self.path, encoding="utf-8")
            formatter = logging.Formatter(
                fmt="%(asctime)s | %(levelname)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)

    def log(self, category: str, message: str) -> None:
        """Log a categorized message."""

        self.logger.info("[%s] %s", category.upper(), message)

    def recent_entries(self, limit: int = 50) -> list[str]:
        """Return recent log lines."""

        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        return lines[-limit:]

    def export_report(self, destination: Path, limit: int = 500) -> Path:
        """Export recent logs to a readable report."""

        lines = self.recent_entries(limit=limit)
        report = "Zeph Activity Report\n" + "=" * 40 + "\n" + "\n".join(lines)
        destination.write_text(report, encoding="utf-8")
        return destination
