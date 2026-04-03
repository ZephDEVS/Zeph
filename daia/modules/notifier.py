"""Desktop notifications and task sounds."""

from __future__ import annotations

import platform
import subprocess


class Notifier:
    """Sends toast notifications and optional system sounds."""

    def notify(self, title: str, message: str, timeout: int = 5) -> None:
        """Send a desktop notification."""

        system = platform.system()
        if system == "Darwin":
            try:
                escaped_title = title.replace('"', '\\"')
                escaped_message = message.replace('"', '\\"')
                subprocess.run(
                    [
                        "osascript",
                        "-e",
                        f'display notification "{escaped_message}" with title "{escaped_title}"',
                    ],
                    check=False,
                )
            except Exception:
                return
            return

        try:
            from plyer import notification

            notification.notify(
                title=title,
                message=message,
                app_name="Zeph",
                timeout=timeout,
            )
            return
        except Exception:
            pass

        try:
            if system == "Linux":
                subprocess.run(["notify-send", title, message], check=False)
        except Exception:
            # Notifications are best-effort only and should never crash the agent.
            return

    def play_sound(self, success: bool = True) -> None:
        """Play a basic platform-native alert sound."""

        system = platform.system()
        try:
            if system == "Darwin":
                sound = "Glass" if success else "Basso"
                subprocess.run(["afplay", f"/System/Library/Sounds/{sound}.aiff"], check=False)
            elif system == "Linux":
                subprocess.run(["paplay", "/usr/share/sounds/freedesktop/stereo/complete.oga"], check=False)
            elif system == "Windows":
                import winsound

                winsound.MessageBeep(winsound.MB_ICONASTERISK if success else winsound.MB_ICONHAND)
        except Exception:
            pass
