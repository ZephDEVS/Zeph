"""Voice input, wake word detection, and speech output."""

from __future__ import annotations

import tempfile
import threading
from pathlib import Path
from typing import Callable

import pyttsx3
import speech_recognition as sr


class VoiceAssistant:
    """Wraps speech recognition and offline TTS."""

    def __init__(self, wake_word: str = "Hey DAIA", voice_rate: int = 180, language: str = "en-US") -> None:
        self.wake_word = wake_word.lower()
        self.language = language
        self.recognizer = sr.Recognizer()
        self.tts = pyttsx3.init()
        self.tts.setProperty("rate", voice_rate)

    def speak(self, text: str) -> None:
        """Speak text aloud."""

        self.tts.say(text)
        self.tts.runAndWait()

    def listen_once(self, timeout: int = 5, phrase_time_limit: int = 12) -> str:
        """Capture one utterance and convert it to text."""

        with sr.Microphone() as source:
            self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
            audio = self.recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
        try:
            return self.recognizer.recognize_google(audio, language=self.language)
        except Exception:
            return self._fallback_whisper(audio)

    def _fallback_whisper(self, audio: sr.AudioData) -> str:
        """Try local Whisper CLI if installed."""

        raw_data = audio.get_wav_data()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as handle:
            handle.write(raw_data)
            temp_path = Path(handle.name)
        try:
            import subprocess

            result = subprocess.run(
                ["whisper", str(temp_path), "--model", "base", "--language", self.language.split("-")[0], "--output_format", "txt"],
                capture_output=True,
                text=True,
                check=False,
            )
            txt_path = temp_path.with_suffix(".txt")
            if txt_path.exists():
                return txt_path.read_text(encoding="utf-8").strip()
            return result.stdout.strip()
        finally:
            temp_path.unlink(missing_ok=True)

    def wait_for_wake_word(
        self,
        command_callback: Callable[[str], None],
        stop_event: threading.Event | None = None,
    ) -> threading.Thread:
        """Listen continuously for the wake word, then capture the next command."""

        def loop() -> None:
            while stop_event is None or not stop_event.is_set():
                try:
                    heard = self.listen_once(timeout=5, phrase_time_limit=4)
                except Exception:
                    continue
                if self.wake_word not in heard.lower():
                    continue
                try:
                    command = self.listen_once(timeout=5, phrase_time_limit=12)
                    command_callback(command)
                except Exception:
                    continue

        thread = threading.Thread(target=loop, daemon=True)
        thread.start()
        return thread
