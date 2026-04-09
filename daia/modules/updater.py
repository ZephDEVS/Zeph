"""Simple macOS app update checking and installation."""

from __future__ import annotations

import json
import os
import shlex
import stat
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from daia.config import APP_DIR
from daia.version import APP_VERSION, DEFAULT_UPDATE_MANIFEST_URL


@dataclass(slots=True)
class UpdateInfo:
    """Represents the remote release state for Zeph."""

    current_version: str
    latest_version: str
    available: bool
    manifest_url: str
    download_url: str = ""
    notes_url: str = ""
    title: str = ""
    summary: str = ""
    checked_at: float = 0.0
    install_supported: bool = False
    downloaded_path: str = ""
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AppUpdater:
    """Checks a remote manifest and installs newer Zeph app builds."""

    def __init__(self, manifest_url: str = DEFAULT_UPDATE_MANIFEST_URL) -> None:
        self.manifest_url = manifest_url
        self.current_version = APP_VERSION
        self.updates_dir = APP_DIR / "updates"
        self.updates_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _version_tuple(version: str) -> tuple[int, ...]:
        pieces = []
        for part in version.split("."):
            digits = "".join(ch for ch in part if ch.isdigit())
            pieces.append(int(digits or "0"))
        return tuple(pieces)

    def current_app_path(self) -> Path | None:
        """Return the current app bundle path when running as a packaged macOS app."""

        executable = Path(sys.executable).resolve()
        if ".app/Contents/MacOS/" not in str(executable):
            return None
        return executable.parents[2]

    def install_supported(self) -> bool:
        app_path = self.current_app_path()
        return sys.platform == "darwin" and app_path is not None

    def _fetch_manifest(self) -> dict[str, Any]:
        with urllib.request.urlopen(self.manifest_url, timeout=8.0) as response:
            return json.loads(response.read().decode("utf-8"))

    def _resolve_url(self, candidate: str) -> str:
        return urllib.parse.urljoin(self.manifest_url, candidate)

    def check_for_update(self) -> UpdateInfo:
        """Fetch remote release metadata and compare it to the current version."""

        payload = self._fetch_manifest()
        latest = str(payload.get("version", "")).strip() or self.current_version
        download_url = self._resolve_url(str(payload.get("download_url", "")).strip())
        notes_url = self._resolve_url(str(payload.get("notes_url", "")).strip()) if payload.get("notes_url") else ""
        available = self._version_tuple(latest) > self._version_tuple(self.current_version)
        message = f"Zeph {latest} is available." if available else f"Zeph {self.current_version} is up to date."
        return UpdateInfo(
            current_version=self.current_version,
            latest_version=latest,
            available=available,
            manifest_url=self.manifest_url,
            download_url=download_url,
            notes_url=notes_url,
            title=str(payload.get("title", "")).strip(),
            summary=str(payload.get("summary", "")).strip(),
            checked_at=payload.get("checked_at", 0) or 0,
            install_supported=self.install_supported(),
            message=message,
        )

    def download_update(self, info: UpdateInfo) -> Path:
        """Download the update archive to Zeph's app directory."""

        if not info.download_url:
            raise RuntimeError("The update feed did not include a download URL.")
        target = self.updates_dir / f"Zeph-{info.latest_version}.app.zip"
        with urllib.request.urlopen(info.download_url, timeout=30.0) as response:
            with target.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
        return target

    @staticmethod
    def _find_app_bundle(root: Path) -> Path:
        matches = list(root.glob("*.app"))
        if not matches:
            raise RuntimeError("The downloaded archive did not contain Zeph.app.")
        return matches[0]

    def _write_install_script(self, source_app: Path, target_app: Path, workspace: Path) -> Path:
        target_parent = target_app.parent
        temp_target = target_parent / f"{target_app.name}.new"
        backup_target = target_parent / f"{target_app.name}.old"
        script = workspace / "install_update.sh"
        direct_install = os.access(target_parent, os.W_OK)

        if direct_install:
            install_body = "\n".join(
                [
                    f'while pgrep -f {shlex.quote(str(target_app / "Contents/MacOS/Zeph"))} >/dev/null 2>&1; do sleep 1; done',
                    f'rm -rf {shlex.quote(str(temp_target))} {shlex.quote(str(backup_target))}',
                    f'ditto {shlex.quote(str(source_app))} {shlex.quote(str(temp_target))}',
                    f'mv {shlex.quote(str(target_app))} {shlex.quote(str(backup_target))}',
                    f'mv {shlex.quote(str(temp_target))} {shlex.quote(str(target_app))}',
                    f'open {shlex.quote(str(target_app))}',
                    f'rm -rf {shlex.quote(str(backup_target))} {shlex.quote(str(workspace))}',
                ]
            )
        else:
            privileged_command = json.dumps(
                " && ".join(
                    [
                        f"rm -rf {shlex.quote(str(temp_target))} {shlex.quote(str(backup_target))}",
                        f"ditto {shlex.quote(str(source_app))} {shlex.quote(str(temp_target))}",
                        f"mv {shlex.quote(str(target_app))} {shlex.quote(str(backup_target))}",
                        f"mv {shlex.quote(str(temp_target))} {shlex.quote(str(target_app))}",
                    ]
                )
            )
            install_body = "\n".join(
                [
                    f'while pgrep -f {shlex.quote(str(target_app / "Contents/MacOS/Zeph"))} >/dev/null 2>&1; do sleep 1; done',
                    "osascript <<'APPLESCRIPT'",
                    f"do shell script {privileged_command} with administrator privileges",
                    "APPLESCRIPT",
                    f'open {shlex.quote(str(target_app))}',
                    f'rm -rf {shlex.quote(str(backup_target))} {shlex.quote(str(workspace))}',
                ]
            )

        script.write_text(
            "#!/bin/zsh\n"
            "set -euo pipefail\n"
            f"{install_body}\n",
            encoding="utf-8",
        )
        current_mode = script.stat().st_mode
        script.chmod(current_mode | stat.S_IXUSR)
        return script

    def install_update(self, info: UpdateInfo) -> dict[str, Any]:
        """Download and install the newest Zeph app when possible."""

        archive = self.download_update(info)
        app_path = self.current_app_path()
        if app_path is None:
            return {
                "ok": True,
                "mode": "download_only",
                "message": f"Downloaded Zeph {info.latest_version} to {archive}. Replace your current app manually.",
                "downloadedPath": str(archive),
            }

        workspace = Path(tempfile.mkdtemp(prefix="zeph-update-", dir=self.updates_dir))
        with zipfile.ZipFile(archive) as handle:
            handle.extractall(workspace)
        source_app = self._find_app_bundle(workspace)
        script = self._write_install_script(source_app, app_path, workspace)
        subprocess.Popen(
            ["/bin/zsh", str(script)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return {
            "ok": True,
            "mode": "install_started",
            "message": f"Installing Zeph {info.latest_version} now.",
            "downloadedPath": str(archive),
        }
