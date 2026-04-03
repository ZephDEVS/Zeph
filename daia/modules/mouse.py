"""Mouse control helpers."""

from __future__ import annotations

from typing import Literal

import pyautogui


ButtonName = Literal["left", "right", "middle"]


class MouseController:
    """Provides human-like mouse operations."""

    def __init__(self, speed_multiplier: float = 1.0) -> None:
        pyautogui.FAILSAFE = True
        self.speed_multiplier = max(speed_multiplier, 0.1)

    def move_to(self, x: int, y: int, duration: float = 0.4) -> None:
        """Move the pointer smoothly to a screen coordinate."""

        pyautogui.moveTo(
            x,
            y,
            duration=max(0.05, duration / self.speed_multiplier),
            tween=pyautogui.easeInOutQuad,
        )

    def click(self, x: int | None = None, y: int | None = None, button: ButtonName = "left") -> None:
        """Click a location with optional pre-move."""

        if x is not None and y is not None:
            self.move_to(x, y)
        pyautogui.click(button=button)

    def double_click(self, x: int | None = None, y: int | None = None) -> None:
        """Perform a double click."""

        if x is not None and y is not None:
            self.move_to(x, y)
        pyautogui.doubleClick()

    def drag(self, start_x: int, start_y: int, end_x: int, end_y: int, duration: float = 0.8) -> None:
        """Drag from one coordinate to another."""

        self.move_to(start_x, start_y, duration=duration / 2)
        pyautogui.dragTo(
            end_x,
            end_y,
            duration=max(0.1, duration / self.speed_multiplier),
            tween=pyautogui.easeInOutQuad,
            button="left",
        )

    def scroll(self, amount: int, x: int | None = None, y: int | None = None) -> None:
        """Scroll at the current or a target position."""

        if x is not None and y is not None:
            self.move_to(x, y)
        pyautogui.scroll(amount)

    def position(self) -> tuple[int, int]:
        """Return current pointer coordinates."""

        pos = pyautogui.position()
        return pos.x, pos.y
