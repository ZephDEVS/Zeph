"""Application launching and process management."""

from __future__ import annotations

import platform
import subprocess
import threading
import time
from typing import Callable

import psutil


class AppsManager:
    """Launches apps and manages processes."""

    def is_running(self, app_name: str) -> bool:
        needle = app_name.lower()
        return any(needle in (proc.info["name"] or "").lower() for proc in psutil.process_iter(["name"]))

    def open_app(self, app_name: str) -> str:
        """Launch an app if it is not already running."""

        if self.is_running(app_name):
            return f"{app_name} is already running."
        system = platform.system()
        if system == "Darwin":
            subprocess.run(["open", "-a", app_name], check=False)
        elif system == "Windows":
            subprocess.Popen(["cmd", "/c", "start", "", app_name])  # noqa: S603,S607
        else:
            subprocess.Popen([app_name])  # noqa: S603,S607
        return f"Launch requested for {app_name}."

    def close_app(self, app_name: str, force: bool = False) -> int:
        """Close an app by name and return affected process count."""

        killed = 0
        for proc in psutil.process_iter(["pid", "name"]):
            name = (proc.info["name"] or "").lower()
            if app_name.lower() not in name:
                continue
            try:
                if force:
                    proc.kill()
                else:
                    proc.terminate()
                killed += 1
            except psutil.Error:
                continue
        return killed

    def list_processes(self) -> list[dict[str, float | int | str]]:
        """Return process stats."""

        processes = []
        for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
            try:
                processes.append(
                    {
                        "pid": proc.info["pid"],
                        "name": proc.info["name"] or "",
                        "cpu_percent": proc.info["cpu_percent"] or 0.0,
                        "memory_percent": round(proc.info["memory_percent"] or 0.0, 2),
                    }
                )
            except psutil.Error:
                continue
        processes.sort(key=lambda item: float(item["cpu_percent"]), reverse=True)
        return processes

    def kill_process(self, pid: int | None = None, name: str | None = None) -> int:
        """Kill a process by PID or name."""

        affected = 0
        for proc in psutil.process_iter(["pid", "name"]):
            matches = (pid is not None and proc.info["pid"] == pid) or (
                name is not None and name.lower() in (proc.info["name"] or "").lower()
            )
            if not matches:
                continue
            try:
                proc.kill()
                affected += 1
            except psutil.Error:
                continue
        return affected

    def system_resources(self) -> dict[str, float]:
        """Return CPU, memory, and disk usage."""

        return {
            "cpu_percent": psutil.cpu_percent(interval=0.2),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_percent": psutil.disk_usage("/").percent,
        }

    def monitor_thresholds(
        self,
        cpu_threshold: float,
        ram_threshold: float,
        callback: Callable[[dict[str, float | int | str]], None],
        interval: float = 5.0,
    ) -> threading.Thread:
        """Monitor processes and alert via callback when thresholds are exceeded."""

        def worker() -> None:
            while True:
                for proc in self.list_processes():
                    if float(proc["cpu_percent"]) >= cpu_threshold or float(proc["memory_percent"]) >= ram_threshold:
                        callback(proc)
                time.sleep(interval)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        return thread
