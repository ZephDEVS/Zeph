"""Filesystem operations and monitoring."""

from __future__ import annotations

import fnmatch
import os
import platform
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


class FileWatcherHandler(FileSystemEventHandler):
    """Dispatches filesystem events to a callback."""

    def __init__(self, callback: Callable[[str], None]) -> None:
        self.callback = callback

    def on_any_event(self, event) -> None:  # type: ignore[override]
        self.callback(f"{event.event_type}: {event.src_path}")


class FilesystemManager:
    """Handles file and folder operations."""

    def __init__(self) -> None:
        self._observers: dict[str, Observer] = {}

    def create_file(self, path: str | Path, content: str = "") -> Path:
        file_path = Path(path).expanduser()
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return file_path

    def read_file(self, path: str | Path) -> str:
        return Path(path).expanduser().read_text(encoding="utf-8")

    def create_folder(self, path: str | Path) -> Path:
        folder = Path(path).expanduser()
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def rename(self, src: str | Path, dest: str | Path) -> Path:
        return Path(src).expanduser().rename(Path(dest).expanduser())

    def move(self, src: str | Path, dest: str | Path) -> Path:
        target = shutil.move(str(Path(src).expanduser()), str(Path(dest).expanduser()))
        return Path(target)

    def copy(self, src: str | Path, dest: str | Path) -> Path:
        src_path = Path(src).expanduser()
        dest_path = Path(dest).expanduser()
        if src_path.is_dir():
            shutil.copytree(src_path, dest_path, dirs_exist_ok=True)
        else:
            shutil.copy2(src_path, dest_path)
        return dest_path

    def delete(self, path: str | Path) -> None:
        target = Path(path).expanduser()
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()

    def search(
        self,
        root: str | Path,
        pattern: str = "*",
        extension: str | None = None,
        contains_text: str | None = None,
    ) -> list[Path]:
        root_path = Path(root).expanduser()
        results: list[Path] = []
        for file_path in root_path.rglob("*"):
            if extension and file_path.suffix.lower() != extension.lower():
                continue
            if not fnmatch.fnmatch(file_path.name, pattern):
                continue
            if contains_text and file_path.is_file():
                try:
                    content = file_path.read_text(encoding="utf-8", errors="ignore")
                    if contains_text not in content:
                        continue
                except Exception:
                    continue
            results.append(file_path)
        return results

    def bulk_rename(self, root: str | Path, pattern: str, replacement: str) -> list[tuple[str, str]]:
        root_path = Path(root).expanduser()
        renamed: list[tuple[str, str]] = []
        for file_path in root_path.iterdir():
            if pattern not in file_path.name:
                continue
            new_name = file_path.name.replace(pattern, replacement)
            new_path = file_path.with_name(new_name)
            file_path.rename(new_path)
            renamed.append((str(file_path), str(new_path)))
        return renamed

    def watch(self, root: str | Path, callback: Callable[[str], None]) -> str:
        root_path = str(Path(root).expanduser())
        observer = Observer()
        observer.schedule(FileWatcherHandler(callback), root_path, recursive=True)
        observer.daemon = True
        observer.start()
        self._observers[root_path] = observer
        return root_path

    def stop_watch(self, root: str | Path) -> None:
        root_path = str(Path(root).expanduser())
        observer = self._observers.pop(root_path, None)
        if observer:
            observer.stop()
            observer.join(timeout=2)

    def open_default(self, path: str | Path) -> None:
        target = str(Path(path).expanduser())
        system = platform.system()
        if system == "Darwin":
            subprocess.run(["open", target], check=False)
        elif system == "Windows":
            os.startfile(target)  # type: ignore[attr-defined]
        else:
            subprocess.run(["xdg-open", target], check=False)
