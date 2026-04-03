"""Screen capture, OCR, and monitor discovery."""

from __future__ import annotations

import ctypes
import platform
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import pyautogui
import pytesseract
from PIL import Image, ImageGrab


class ScreenReader:
    """Provides screen capture, OCR, and monitor information."""

    def screenshot(
        self,
        region: tuple[int, int, int, int] | None = None,
        save_path: str | Path | None = None,
        monitor_index: int | None = None,
    ) -> Image.Image:
        """Capture the whole screen, a region, or a specific monitor."""

        bbox = region
        if monitor_index is not None:
            monitor = self.detect_monitors()[monitor_index]
            bbox = (monitor["x"], monitor["y"], monitor["x"] + monitor["width"], monitor["y"] + monitor["height"])
        if platform.system() == "Darwin":
            return self._screencapture_macos(bbox=bbox, save_path=save_path)
        image = ImageGrab.grab(bbox=bbox, all_screens=True)
        if save_path:
            image.save(save_path)
        return image

    def read_text(
        self,
        region: tuple[int, int, int, int] | None = None,
        monitor_index: int | None = None,
    ) -> str:
        """Run OCR on a screen region."""

        image = self.screenshot(region=region, monitor_index=monitor_index)
        return self._extract_text(image).strip()

    def locate_image(
        self,
        template_path: str | Path,
        confidence: float = 0.8,
        retries: int = 3,
    ) -> Any:
        """Locate an image on screen with retry logic."""

        for _ in range(retries):
            match = pyautogui.locateOnScreen(str(template_path), confidence=confidence)
            if match:
                return match
            time.sleep(0.5)
        return None

    def describe_screen(self, monitor_index: int | None = None) -> str:
        """Describe visible text and high-level context."""

        image = self.screenshot(monitor_index=monitor_index)
        text = self._extract_text(image).strip()
        if not text:
            return "I can see the current screen, but OCR did not detect readable text."
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        preview = "; ".join(lines[:8])
        return f"Visible text includes: {preview}"

    def _extract_text(self, image: Image.Image) -> str:
        """Use Tesseract when available, otherwise fall back to platform OCR."""

        if shutil.which("tesseract"):
            return pytesseract.image_to_string(image)
        if platform.system() == "Darwin":
            return self._vision_ocr_macos(image)
        return ""

    def _vision_ocr_macos(self, image: Image.Image) -> str:
        """Use Apple's Vision framework for OCR when Tesseract is unavailable."""

        try:
            from Foundation import NSURL
            import Vision
        except Exception:
            return ""

        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
                temp_path = Path(handle.name)
            image.save(temp_path)
            request = Vision.VNRecognizeTextRequest.alloc().init()
            request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
            request.setUsesLanguageCorrection_(True)
            handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(
                NSURL.fileURLWithPath_(str(temp_path)),
                {},
            )
            result = handler.performRequests_error_([request], None)
            if isinstance(result, tuple):
                success = bool(result[0])
            else:
                success = bool(result)
            if not success:
                return ""
            observations = request.results() or []
            lines: list[str] = []
            for observation in observations:
                candidates = observation.topCandidates_(1)
                if candidates:
                    lines.append(str(candidates[0].string()))
            return "\n".join(lines)
        except Exception:
            return ""
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def _screencapture_macos(
        self,
        bbox: tuple[int, int, int, int] | None = None,
        save_path: str | Path | None = None,
    ) -> Image.Image:
        """Capture the screen using macOS's native screencapture utility."""

        temp_path: Path | None = None
        target_path = Path(save_path) if save_path else None
        try:
            if target_path is None:
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
                    temp_path = Path(handle.name)
                target_path = temp_path
            else:
                target_path.parent.mkdir(parents=True, exist_ok=True)
            command = ["screencapture", "-x"]
            if bbox is not None:
                left, top, right, bottom = bbox
                width = right - left
                height = bottom - top
                command.extend(["-R", f"{left},{top},{width},{height}"])
            command.append(str(target_path))
            result = subprocess.run(command, capture_output=True, text=True, check=False)
            if result.returncode != 0 or not target_path.exists() or target_path.stat().st_size == 0:
                raise RuntimeError(
                    "Screen capture failed. On macOS, grant Screen Recording permission to Terminal or Codex and try again."
                )
            return Image.open(target_path).copy()
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def detect_monitors(self) -> list[dict[str, int | str]]:
        """Return connected monitor bounds."""

        system = platform.system()
        if system == "Windows":
            return self._detect_monitors_windows()
        if system == "Darwin":
            return self._detect_monitors_macos()
        return self._detect_monitors_linux()

    def _detect_monitors_windows(self) -> list[dict[str, int | str]]:
        monitors: list[dict[str, int | str]] = []

        def callback(hmonitor, _hdc, rect_ptr, _lparam):
            rect = rect_ptr.contents
            monitors.append(
                {
                    "name": f"Monitor {len(monitors) + 1}",
                    "x": rect.left,
                    "y": rect.top,
                    "width": rect.right - rect.left,
                    "height": rect.bottom - rect.top,
                }
            )
            return 1

        class Rect(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

        monitor_enum_proc = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.POINTER(Rect), ctypes.c_double)
        ctypes.windll.user32.EnumDisplayMonitors(0, 0, monitor_enum_proc(callback), 0)
        return monitors or [{"name": "Primary", "x": 0, "y": 0, "width": pyautogui.size().width, "height": pyautogui.size().height}]

    def _detect_monitors_macos(self) -> list[dict[str, int | str]]:
        try:
            result = subprocess.run(
                [
                    "system_profiler",
                    "SPDisplaysDataType",
                    "-json",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            # Exact geometry is awkward via system_profiler; fall back to primary resolution if needed.
            width, height = pyautogui.size()
            return [{"name": "Primary", "x": 0, "y": 0, "width": width, "height": height, "raw": result.stdout[:400]}]
        except Exception:
            width, height = pyautogui.size()
            return [{"name": "Primary", "x": 0, "y": 0, "width": width, "height": height}]

    def _detect_monitors_linux(self) -> list[dict[str, int | str]]:
        try:
            result = subprocess.run(["xrandr", "--listmonitors"], capture_output=True, text=True, check=False)
            monitors: list[dict[str, int | str]] = []
            for line in result.stdout.splitlines():
                if ":" not in line or "+" not in line or "Monitors" in line:
                    continue
                parts = line.split()
                geometry = parts[2]
                size_part, offset_part = geometry.split("+", 1)
                width, height = [int(value.split("/")[0]) for value in size_part.split("x")]
                x, y = [int(value) for value in offset_part.split("+")]
                monitors.append({"name": parts[-1], "x": x, "y": y, "width": width, "height": height})
            if monitors:
                return monitors
        except Exception:
            pass
        width, height = pyautogui.size()
        return [{"name": "Primary", "x": 0, "y": 0, "width": width, "height": height}]
