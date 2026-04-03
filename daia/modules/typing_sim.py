"""Human-like typing simulation."""

from __future__ import annotations

import random
import string
import time
from dataclasses import dataclass

import pyautogui
from pynput.keyboard import Controller as KeyboardController
from pynput.keyboard import Key


@dataclass(slots=True)
class TypingProfile:
    """Typing behavior configuration."""

    wpm: int = 80
    jitter: float = 0.30
    typo_rate: float = 0.02
    punctuation_pause_min: float = 0.3
    punctuation_pause_max: float = 0.8
    speed_multiplier: float = 1.0
    stealth_mode: bool = False


class TypingSimulator:
    """Types text with realistic timing and typo correction."""

    def __init__(self, profile: TypingProfile | None = None) -> None:
        self.profile = profile or TypingProfile()
        self.keyboard = KeyboardController()

    def set_profile(self, profile: TypingProfile) -> None:
        """Replace the active typing profile."""

        self.profile = profile

    def _base_delay(self) -> float:
        chars_per_second = max((self.profile.wpm * 5) / 60.0, 0.1)
        return max(0.01, 1.0 / chars_per_second) / max(self.profile.speed_multiplier, 0.1)

    def _delay_for_character(self, char: str) -> float:
        base = self._base_delay()
        jitter_scale = self.profile.jitter * (1.6 if self.profile.stealth_mode else 1.0)
        delay = base * random.uniform(1.0 - jitter_scale, 1.0 + jitter_scale)
        if char in ",.\n;:!?":
            delay += random.uniform(
                self.profile.punctuation_pause_min,
                self.profile.punctuation_pause_max,
            )
        return max(0.01, delay)

    @staticmethod
    def _neighbor_char(char: str) -> str:
        pool = string.ascii_lowercase if char.islower() else string.ascii_uppercase
        if char.isdigit():
            pool = string.digits
        if not pool:
            pool = string.ascii_lowercase
        return random.choice(pool)

    def _press_unicode(self, char: str) -> None:
        try:
            self.keyboard.type(char)
        except Exception:
            pyautogui.write(char, interval=0.0)

    def type_text(self, text: str) -> dict[str, int | float]:
        """Type the full text and return statistics."""

        typed_chars = 0
        corrections = 0
        start = time.perf_counter()
        for char in text:
            if char and random.random() < self.profile.typo_rate and char.isalnum():
                typo = self._neighbor_char(char)
                self._press_unicode(typo)
                time.sleep(self._delay_for_character(typo))
                self.keyboard.press(Key.backspace)
                self.keyboard.release(Key.backspace)
                corrections += 1
                time.sleep(random.uniform(0.04, 0.12))
            self._press_unicode(char)
            typed_chars += 1
            time.sleep(self._delay_for_character(char))
        elapsed = time.perf_counter() - start
        return {"typed_chars": typed_chars, "corrections": corrections, "elapsed": round(elapsed, 2)}
