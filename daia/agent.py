"""Core agent orchestration, planning, and task routing."""

from __future__ import annotations

import json
import os
import platform
import random
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from rich.console import Console
from rich.panel import Panel

from daia.config import APP_DIR, SCRIPTS_DIR, AgentConfig, ConfigManager
from daia.memory import MemoryStore
from daia.modules.apps import AppsManager
from daia.modules.browser import BrowserController
from daia.modules.clipboard import ClipboardManager
from daia.modules.files import FilesystemManager
from daia.modules.logger import ActivityLogger
from daia.modules.mouse import MouseController
from daia.modules.notifier import Notifier
from daia.modules.scheduler import SchedulerService
from daia.modules.screen import ScreenReader
from daia.modules.typing_sim import TypingProfile, TypingSimulator
from daia.modules.voice import VoiceAssistant
from daia.modules.windows import WindowManager


@dataclass(slots=True)
class ExecutionContext:
    """Runtime flags for a single task."""

    dry_run: bool = False
    speed_multiplier: float = 1.0
    risk_level: str = "low"


class ZephAgent:
    """High-level desktop AI agent implementation."""

    SPEED_MAP = {
        "slow": 0.5,
        "normal": 1.0,
        "fast": 2.0,
        "stealth": 0.25,
    }

    def __init__(
        self,
        console: Console | None = None,
        event_callback: Callable[[str, dict[str, Any]], None] | None = None,
        confirm_handler: Callable[[str], bool] | None = None,
        plan_handler: Callable[[list[str]], bool] | None = None,
    ) -> None:
        self.console = console or Console()
        self.event_callback = event_callback
        self.confirm_handler = confirm_handler
        self.plan_handler = plan_handler
        self.config_manager = ConfigManager()
        self.config = self.config_manager.load()
        self.memory = MemoryStore()
        self.logger = ActivityLogger()
        self.notifier = Notifier()
        self.screen = ScreenReader()
        self.windows = WindowManager()
        self.files = FilesystemManager()
        self.apps = AppsManager()
        self.browser = BrowserController()
        self.typing = TypingSimulator(self._typing_profile())
        self.mouse = MouseController(speed_multiplier=self.config.speed_multiplier)
        self.clipboard = ClipboardManager(self.memory, limit=self.config.clipboard_history_limit)
        self.voice = VoiceAssistant(
            wake_word=self.config.wake_word,
            voice_rate=self.config.voice_rate,
            language=self.config.voice_language,
        )
        self.scheduler = SchedulerService(self.memory, callback=self._run_scheduled_payload)
        self.scheduler.start()

    def _emit(self, event_type: str, **payload: Any) -> None:
        """Send a structured event to an attached interface."""

        if self.event_callback is None:
            return
        try:
            self.event_callback(event_type, payload)
        except Exception:
            return

    def _typing_profile(self) -> TypingProfile:
        stealth = self.config.speed_mode == "stealth"
        return TypingProfile(
            wpm=self.config.preferred_wpm,
            typo_rate=self.config.typing_typo_rate,
            speed_multiplier=self.config.speed_multiplier,
            stealth_mode=stealth,
        )

    def startup_status(self) -> dict[str, Any]:
        """Collect startup banner information."""

        return {
            "agent_name": self.config.agent_name,
            "os": platform.platform(),
            "monitors": self.screen.detect_monitors(),
            "db_path": str(self.memory.db_path),
            "scheduled_tasks": len(self.scheduler.list_tasks()),
            "recent_activity": self.memory.summarize_recent_activity(),
        }

    def first_run_setup(self) -> AgentConfig:
        """Prompt for initial settings and persist them."""

        if self.config_manager.exists():
            return self.config
        self.console.print(Panel.fit("Welcome to Zeph. Let's configure your desktop agent."))
        user_name = input("Your name: ").strip()
        api_key = input("Preferred AI model API key: ").strip()
        preferred_wpm = int(input("Preferred typing speed (WPM, default 80): ").strip() or "80")
        wake_word = input("Wake word (default Hey DAIA): ").strip() or "Hey DAIA"
        self.config.user_name = user_name
        self.config.api_key = api_key
        self.config.preferred_wpm = preferred_wpm
        self.config.wake_word = wake_word
        self.config_manager.save(self.config)
        self.memory.set_preference("user_name", user_name)
        self.memory.set_preference("preferred_wpm", preferred_wpm)
        self.memory.set_preference("wake_word", wake_word)
        return self.config

    def announce(self, text: str, speak: bool = False) -> None:
        """Print and optionally speak a short announcement."""

        self.console.print(f"[bold cyan]{self.config.agent_name}[/bold cyan]: {text}")
        self._emit("announce", text=text, speak=speak)
        if speak:
            try:
                self.voice.speak(text)
            except Exception:
                pass

    def build_plan(self, goal: str) -> list[str]:
        """Break a goal into a plan using the configured AI model or heuristics."""

        ai_plan = self._ai_plan(goal)
        if ai_plan:
            return ai_plan
        if "google docs" in goal.lower():
            return [
                "Generate the requested essay content.",
                "Open Google Docs and create a new document.",
                "Type the essay using the human typing simulator.",
                "Save the document and report the result.",
            ]
        return [
            "Inspect the current environment and gather context.",
            "Execute the requested steps in order.",
            "Verify the result and report back.",
        ]

    def _ai_plan(self, goal: str) -> list[str] | None:
        api_key = self.config.api_key or os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not api_key:
            return None
        prompt = (
            "Break this desktop automation goal into 4-7 concise ordered steps. "
            "Return JSON only as {\"steps\": [\"...\"]}. Goal: "
            + goal
        )
        try:
            if "claude" in self.config.ai_model.lower():
                import anthropic

                client = anthropic.Anthropic(api_key=api_key)
                response = client.messages.create(
                    model=self.config.ai_model,
                    max_tokens=400,
                    messages=[{"role": "user", "content": prompt}],
                )
                text = "".join(block.text for block in response.content if getattr(block, "type", "") == "text")
            else:
                from openai import OpenAI

                client = OpenAI(api_key=api_key)
                response = client.responses.create(model=self.config.ai_model, input=prompt)
                text = response.output_text
            parsed = json.loads(text)
            steps = parsed.get("steps", [])
            return [str(step) for step in steps if str(step).strip()]
        except Exception:
            return None

    def ask_to_proceed(self, steps: list[str]) -> bool:
        """Display a plan and prompt the user."""

        self.console.print("[bold]Here's my plan:[/bold]")
        for idx, step in enumerate(steps, start=1):
            self.console.print(f"{idx}. {step}")
        self._emit("plan", steps=steps)
        if self.plan_handler is not None:
            return self.plan_handler(steps)
        return input("Shall I proceed? (y/n) ").strip().lower().startswith("y")

    def _confirm(self, prompt: str) -> bool:
        """Prompt the user for a safety confirmation with timeout."""

        self._emit("confirm", prompt=prompt)
        if self.confirm_handler is not None:
            return self.confirm_handler(prompt)
        result = {"value": False}

        def read_input() -> None:
            answer = input(f"I'm about to {prompt} — confirm? (y/n) ").strip().lower()
            result["value"] = answer.startswith("y")

        thread = threading.Thread(target=read_input, daemon=True)
        thread.start()
        thread.join(timeout=15)
        if thread.is_alive():
            self.notifier.notify("Zeph", f"Aborted: no confirmation received for '{prompt}'.")
            return False
        return result["value"]

    def _context_for_command(self, command: str) -> tuple[str, ExecutionContext]:
        dry_run = command.lower().startswith("dry run:")
        cleaned = command.split(":", 1)[1].strip() if dry_run else command.strip()
        context = ExecutionContext(dry_run=dry_run, speed_multiplier=self.config.speed_multiplier)
        return cleaned, context

    def _is_action_request(self, command: str) -> bool:
        """Detect whether a message is asking Zeph to act on the computer."""

        lowered = command.strip().lower()
        if not lowered:
            return False

        explicit_patterns = (
            "what windows",
            "open windows",
            "focus window ",
            "type ",
            "take a screenshot",
            "what you see",
            "delete all",
            "save it to a file",
            "read clipboard",
            "clipboard history",
            "paste clipboard ",
            "kill the process using the most cpu",
            "list processes",
            "kill process ",
            "google docs",
            "google doc",
            "list scheduled tasks",
            "pause scheduled task ",
            "resume scheduled task ",
            "delete scheduled task ",
            "record what i do",
            "spotify",
            "close app ",
            "calendar app",
            "press ",
            "open url ",
            "extract text from ",
            "recent logs",
            "export logs",
            "voice mode",
        )
        if any(pattern in lowered for pattern in explicit_patterns):
            return True

        if lowered.startswith("every "):
            return True

        action_starts = (
            "open ",
            "close ",
            "launch ",
            "start ",
            "stop ",
            "quit ",
            "type ",
            "click ",
            "move ",
            "scroll ",
            "drag ",
            "focus ",
            "switch ",
            "show ",
            "take ",
            "capture ",
            "describe ",
            "read ",
            "copy ",
            "paste ",
            "save ",
            "delete ",
            "remove ",
            "rename ",
            "create ",
            "write ",
            "record ",
            "monitor ",
            "watch ",
            "schedule ",
            "set speed",
        )
        if lowered.startswith(action_starts):
            return True

        polite_action_starts = (
            "can you open ",
            "can you close ",
            "can you type ",
            "can you click ",
            "can you take ",
            "can you show ",
            "can you describe ",
            "can you read ",
            "can you copy ",
            "can you save ",
            "can you delete ",
            "can you kill ",
            "could you open ",
            "could you close ",
            "could you type ",
            "could you click ",
            "could you take ",
            "could you show ",
            "could you describe ",
            "could you read ",
            "could you copy ",
            "could you save ",
            "could you delete ",
            "could you kill ",
            "please open ",
            "please close ",
            "please type ",
            "please click ",
            "please take ",
            "please show ",
            "please describe ",
            "please read ",
            "please copy ",
            "please save ",
            "please delete ",
            "please kill ",
        )
        return lowered.startswith(polite_action_starts)

    def _respond_as_chat(self, command: str) -> str:
        """Handle ordinary conversation without task-execution framing."""

        lowered = command.strip().lower()
        simple = re.sub(r"[^a-z0-9\s]", "", lowered).strip()

        canned: dict[str, str] = {
            "hi": "Hi. What would you like help with?",
            "hello": "Hi. What would you like help with?",
            "hey": "Hey. What can I help you with?",
            "thanks": "You're welcome.",
            "thank you": "You're welcome.",
            "who are you": "I'm Zeph, your local desktop assistant. I can chat normally, and I can also control apps, windows, typing, files, and the browser when you ask.",
            "what can you do": "I can chat with you like a normal assistant, and I can also take actions on your computer like opening apps, reading the screen, typing, managing files, and automating tasks.",
            "help": "You can talk to me normally, or ask me to do something on your computer. For example: 'show my windows', 'take a screenshot and tell me what you see', or 'open Spotify'.",
        }
        if simple in canned:
            return canned[simple]

        prompt = (
            "You are Zeph, a calm and capable desktop assistant with a Claude-like chat style. "
            "Respond conversationally in 1-4 short paragraphs. "
            "Do not mention routers, internal code, tools, or implementation details. "
            "If the user is just greeting you, be warm and brief. "
            "If they ask what you can do, explain that you can chat normally and also act on their computer when asked.\n\n"
            f"User message: {command}"
        )
        ai_text = self._ai_text(prompt)
        if ai_text:
            return ai_text

        if lowered.endswith("?"):
            return "I can help with that. If you want, ask me normally, or ask me to take an action on your computer."
        return "I'm here. If you want, we can talk normally, or you can ask me to do something on your computer."

    def set_speed(self, mode: str) -> str:
        """Update global speed mode."""

        if mode not in self.SPEED_MAP:
            raise ValueError(f"Unsupported speed mode: {mode}")
        self.config.speed_mode = mode
        self.config.speed_multiplier = self.SPEED_MAP[mode]
        self.config_manager.save(self.config)
        self._apply_runtime_config()
        return f"Speed set to {mode} ({self.config.speed_multiplier}x)."

    def execute(self, command: str) -> str:
        """Route and execute a natural-language command."""

        original = command
        command, context = self._context_for_command(command)
        self.logger.log("INPUT", original)
        lowered = command.lower()
        self._emit("command_started", command=original, dry_run=context.dry_run)
        try:
            if not self._is_action_request(command):
                result = self._respond_as_chat(command)
                self._emit("command_finished", command=original, result=result)
                return result

            self.announce("Working on that now.")
            if "speed " in lowered and any(mode in lowered for mode in self.SPEED_MAP):
                for mode in self.SPEED_MAP:
                    if mode in lowered:
                        return self.set_speed(mode)
            if "what windows" in lowered or "open windows" in lowered:
                windows = self.windows.list_windows()
                return "\n".join(window["title"] for window in windows) or "No open windows detected."
            if lowered.startswith("focus window "):
                title = command[len("focus window ") :].strip()
                return self._do_or_simulate(context, f"focus the '{title}' window", lambda: self._focus_window(title))
            if lowered.startswith("type "):
                text = command[5:].strip().strip("'\"")
                return self._do_or_simulate(context, "type text", lambda: self._type_text(text))
            if "screenshot" in lowered and "what you see" in lowered:
                return self._do_or_simulate(context, "take a screenshot and describe the screen", self._describe_screen)
            if lowered.startswith("take a screenshot"):
                return self._do_or_simulate(context, "take a screenshot", self._capture_only)
            if "delete all" in lowered and ".tmp" in lowered:
                downloads = Path.home() / "Downloads"
                return self._delete_tmp_files(downloads, context)
            if "clipboard" in lowered and "save it to a file" in lowered:
                return self._backup_clipboard(command, context)
            if lowered == "read clipboard":
                return self.clipboard.read() or "Clipboard is empty."
            if lowered == "clipboard history":
                history = self.clipboard.history()
                return "\n".join(f"{idx}. {item['content'][:80]}" for idx, item in enumerate(history)) or "Clipboard history is empty."
            if lowered.startswith("paste clipboard "):
                index = int(command.split()[-1])
                content = self.clipboard.paste_history_item(index)
                return f"Copied clipboard history item {index}: {content[:80]}"
            if "kill the process using the most cpu" in lowered:
                return self._kill_top_process(context)
            if lowered == "list processes":
                return self._format_process_table()
            if lowered.startswith("kill process "):
                target = command[len("kill process ") :].strip()
                return self._kill_named_process(target, context)
            if self._is_google_docs_request(lowered) and "essay" in lowered:
                return self._handle_google_docs_essay(command, context)
            if self._is_google_docs_request(lowered):
                return self._handle_google_docs_request(command, context)
            if lowered.startswith("every "):
                scheduled_command = self._extract_scheduled_command(command)
                task = self.scheduler.add_task(command, {"command": scheduled_command})
                return f"Scheduled task {task.task_id} for {task.natural_language}."
            if lowered == "list scheduled tasks":
                return self._list_schedules()
            if lowered.startswith("pause scheduled task "):
                task_id = command.split()[-1]
                self.scheduler.pause_task(task_id)
                return f"Paused scheduled task {task_id}."
            if lowered.startswith("resume scheduled task "):
                task_id = command.split()[-1]
                self.scheduler.resume_task(task_id)
                return f"Resumed scheduled task {task_id}."
            if lowered.startswith("delete scheduled task "):
                task_id = command.split()[-1]
                self.scheduler.delete_task(task_id)
                return f"Deleted scheduled task {task_id}."
            if "record what i do" in lowered and "save it as an automation" in lowered:
                return self._record_automation(context)
            if "open " in lowered and "spotify" in lowered:
                return self._open_spotify_and_search(context)
            if lowered.startswith("open ") and "http" not in lowered and "spotify" not in lowered:
                app_name = command[len("open ") :].strip()
                return self._do_or_simulate(context, f"open {app_name}", lambda: self.apps.open_app(app_name))
            if lowered.startswith("close app "):
                app_name = command[len("close app ") :].strip()
                return self._close_app(app_name, context)
            if "calendar app" in lowered and "open" in lowered:
                return self._open_calendar(context)
            if lowered.startswith("press "):
                return self._press_hotkey_phrase(command[len("press ") :].strip(), context)
            if "copy" == lowered.strip():
                return self._send_hotkey([self._primary_modifier(), "c"])
            if lowered.startswith("open url "):
                url = command[len("open url ") :].strip()
                return self._do_or_simulate(context, f"open {url}", lambda: self._open_url(url))
            if lowered.startswith("extract text from "):
                url = command[len("extract text from ") :].strip()
                return self._do_or_simulate(context, f"extract webpage text from {url}", lambda: self._extract_web_text(url))
            if lowered == "recent logs":
                return "\n".join(self.logger.recent_entries(20)) or "No log entries yet."
            if lowered.startswith("export logs"):
                path = self.logger.export_report(Path.cwd() / "zeph_activity_report.txt")
                return f"Exported logs to {path}."
            if "voice mode" in lowered:
                self.run_voice_loop()
                return "Voice loop started."
            result = self._execute_via_ai_or_fallback(command, context)
            self._emit("command_finished", command=original, result=result)
            return result
        except Exception as exc:
            self.logger.log("AI", f"Command failed: {exc}")
            self.memory.record_task(original, "failed", str(exc))
            self.notifier.notify("Zeph", f"Task failed: {exc}")
            self._emit("command_failed", command=original, error=str(exc))
            return f"That failed because: {exc}"

    def _do_or_simulate(self, context: ExecutionContext, action: str, func) -> str:
        if context.dry_run:
            result = f"Dry run: I would {action}. Estimated risk: {context.risk_level}. Estimated time: 5-15 seconds."
            self._emit("command_finished", action=action, result=result, dry_run=True)
            return result
        result = func()
        self.memory.record_task(action, "completed", str(result))
        self._emit("command_finished", action=action, result=str(result), dry_run=False)
        return str(result)

    def _type_text(self, text: str) -> str:
        self.typing.set_profile(self._typing_profile())
        stats = self.typing.type_text(text)
        try:
            focused = self.windows.focused_window()
            self.memory.set_behavior(focused, "preferred_wpm", self.config.preferred_wpm)
        except Exception:
            pass
        self.logger.log("SYSTEM", f"Typed {stats['typed_chars']} characters.")
        return f"Typed {stats['typed_chars']} characters in {stats['elapsed']} seconds."

    def _capture_only(self) -> str:
        timestamp = int(time.time())
        path = APP_DIR / f"screenshot_{timestamp}.png"
        self.screen.screenshot(save_path=path)
        return f"Saved screenshot to {path}."

    def _describe_screen(self) -> str:
        timestamp = int(time.time())
        path = APP_DIR / f"screenshot_{timestamp}.png"
        self.screen.screenshot(save_path=path)
        description = self.screen.describe_screen()
        self.logger.log("SCREEN", f"Captured screenshot at {path}.")
        return f"Saved screenshot to {path}. {description}"

    def _delete_tmp_files(self, root: Path, context: ExecutionContext) -> str:
        matches = self.files.search(root, pattern="*.tmp")
        if not matches:
            return "No .tmp files found."
        if context.dry_run:
            return f"Dry run: I would delete {len(matches)} .tmp files from {root}."
        if self.config.confirm.delete_file and not self._confirm(f"delete {len(matches)} .tmp files in {root}"):
            return "Delete aborted."
        for file_path in matches:
            self.files.delete(file_path)
        self.logger.log("FILE", f"Deleted {len(matches)} tmp files from {root}.")
        return f"Deleted {len(matches)} .tmp files from {root}."

    def _backup_clipboard(self, command: str, context: ExecutionContext) -> str:
        destination = "clipboard_backup.txt"
        if "called" in command.lower():
            destination = command.split("called", 1)[1].strip().strip(". ")
        content = self.clipboard.read()
        if context.dry_run:
            return f"Dry run: I would save the current clipboard to {destination}."
        path = self.files.create_file(Path.cwd() / destination, content)
        self.logger.log("FILE", f"Saved clipboard to {path}.")
        return f"Saved clipboard to {path}."

    def _kill_top_process(self, context: ExecutionContext) -> str:
        processes = self.apps.list_processes()
        if not processes:
            return "No processes available."
        target = processes[0]
        if context.dry_run:
            return f"Dry run: I would kill PID {target['pid']} ({target['name']}) using the most CPU."
        if self.config.confirm.kill_process and not self._confirm(f"kill PID {target['pid']} ({target['name']})"):
            return "Process kill aborted."
        killed = self.apps.kill_process(pid=int(target["pid"]))
        return f"Killed {killed} process: {target['name']} (PID {target['pid']})."

    def _kill_named_process(self, target: str, context: ExecutionContext) -> str:
        if target.isdigit():
            pid = int(target)
            if context.dry_run:
                return f"Dry run: I would kill PID {pid}."
            if self.config.confirm.kill_process and not self._confirm(f"kill PID {pid}"):
                return "Process kill aborted."
            killed = self.apps.kill_process(pid=pid)
            return f"Killed {killed} process for PID {pid}."
        if context.dry_run:
            return f"Dry run: I would kill processes named {target}."
        if self.config.confirm.kill_process and not self._confirm(f"kill processes named {target}"):
            return "Process kill aborted."
        killed = self.apps.kill_process(name=target)
        return f"Killed {killed} process(es) named {target}."

    def _handle_google_docs_essay(self, command: str, context: ExecutionContext) -> str:
        topic = "the moon landing"
        word_count = 500
        lower = command.lower()
        for fragment in command.split():
            if fragment.isdigit():
                word_count = int(fragment)
                break
        if "about" in lower:
            topic = command.lower().split("about", 1)[1].split("in google docs")[0].strip()
        steps = self.build_plan(command)
        if not self.ask_to_proceed(steps):
            return "Cancelled before execution."
        essay = self.generate_essay(topic, word_count)
        if context.dry_run:
            return f"Dry run: I would generate a {word_count}-word essay on {topic} and type it into Google Docs."
        self.notifier.notify("Zeph", "Preparing Google Docs essay writer.", timeout=3)
        result = self.browser.google_docs_create_and_type(
            essay,
            self.typing,
            headless=False,
            browser_mode=self.config.browser_mode,
        )
        self.logger.log("WEB", f"Created Google Doc at {result['url']}.")
        return f"Essay complete. Final word count: {result['word_count']}. Document URL: {result['url']}"

    @staticmethod
    def _is_google_docs_request(lowered: str) -> bool:
        return "google docs" in lowered or "google doc" in lowered or "docs.new" in lowered

    def _handle_google_docs_request(self, command: str, context: ExecutionContext) -> str:
        content = self._extract_google_docs_content(command)
        if not content:
            content = "New Google Doc"
        if context.dry_run:
            return f"Dry run: I would open a new Google Doc and type: {content[:120]}"
        self.notifier.notify("Zeph", "Opening Google Docs.", timeout=3)
        result = self.browser.google_docs_create_and_type(
            content,
            self.typing,
            headless=False,
            browser_mode=self.config.browser_mode,
        )
        self.logger.log("WEB", f"Created Google Doc at {result['url']}.")
        return f"Google Doc ready. Typed {result['word_count']} words. Document URL: {result['url']}"

    def _extract_google_docs_content(self, command: str) -> str:
        lowered = command.lower()

        quoted = re.search(r"['\"]([^'\"]+)['\"]", command)
        if quoted:
            return quoted.group(1).strip()

        sentence_match = re.search(r"\btype\s+(a|one)\s+sentence\s+(?:about|on)\s+(.+)$", lowered)
        if sentence_match:
            topic = sentence_match.group(2).strip(" .")
            return self._generate_short_text(topic, "sentence")

        paragraph_match = re.search(r"\btype\s+(a|one)\s+paragraph\s+(?:about|on)\s+(.+)$", lowered)
        if paragraph_match:
            topic = paragraph_match.group(2).strip(" .")
            return self._generate_short_text(topic, "paragraph")

        type_match = re.search(r"\btype\s+(.+)$", command, flags=re.IGNORECASE)
        if type_match:
            content = type_match.group(1).strip().rstrip(".")
            for prefix in ("a sentence about ", "a sentence on ", "one sentence about ", "one sentence on "):
                if content.lower().startswith(prefix):
                    return self._generate_short_text(content[len(prefix) :].strip(), "sentence")
            for prefix in ("a paragraph about ", "a paragraph on ", "one paragraph about ", "one paragraph on "):
                if content.lower().startswith(prefix):
                    return self._generate_short_text(content[len(prefix) :].strip(), "paragraph")
            return content

        write_match = re.search(r"\bwrite\s+(.+)$", command, flags=re.IGNORECASE)
        if write_match:
            content = write_match.group(1).strip().rstrip(".")
            for prefix in ("a sentence about ", "a sentence on ", "one sentence about ", "one sentence on "):
                if content.lower().startswith(prefix):
                    return self._generate_short_text(content[len(prefix) :].strip(), "sentence")
            for prefix in ("a paragraph about ", "a paragraph on ", "one paragraph about ", "one paragraph on "):
                if content.lower().startswith(prefix):
                    return self._generate_short_text(content[len(prefix) :].strip(), "paragraph")
            return content

        return ""

    def _generate_short_text(self, topic: str, form: str) -> str:
        clean_topic = topic.strip() or "something interesting"
        if clean_topic in {"anything", "something", "whatever"}:
            clean_topic = "something interesting"
        prompt = (
            f"Write exactly one {form} about {clean_topic}. "
            "Return only the requested text with no introduction or quotation marks."
        )
        ai_text = self._ai_text(prompt)
        if ai_text:
            return ai_text.strip()
        if form == "paragraph":
            return (
                f"{clean_topic.capitalize()} can reveal a lot about how people learn, adapt, and stay curious, "
                "especially when they take a simple idea and explore it with patience and attention."
            )
        return f"{clean_topic.capitalize()} can be surprisingly meaningful when you slow down long enough to notice the details."

    def generate_essay(self, topic: str, word_count: int) -> str:
        """Generate essay content using AI or a deterministic fallback."""

        prompt = (
            f"Write a clear, polished essay about {topic} in about {word_count} words. "
            "Return only the essay body, with a title on the first line."
        )
        ai_text = self._ai_text(prompt)
        if ai_text:
            return ai_text
        paragraphs = [
            f"{topic.title()}",
            f"The story of {topic} remains one of the most important achievements in modern history. "
            f"It combined scientific curiosity, national ambition, and a willingness to solve hard problems step by step.",
            "Behind the public moment of success was a long chain of planning, testing, and collaboration. "
            "Engineers refined hardware, scientists studied risks, and crews trained repeatedly so that each stage of the mission could work under pressure.",
            "The event also mattered culturally because it changed how people imagined the future. "
            "It showed that careful research, public investment, and disciplined teamwork could turn a distant idea into a concrete reality.",
            "Even today, the lessons still apply. Large goals become achievable when teams break them into smaller parts, learn from failure, and keep improving with patience and precision.",
        ]
        text = "\n\n".join(paragraphs)
        words = text.split()
        while len(words) < word_count:
            words.extend(random.choice(paragraphs[1:]).split())
        return " ".join(words[:word_count])

    def _ai_text(self, prompt: str) -> str | None:
        api_key = self.config.api_key or os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not api_key:
            return None
        try:
            if "claude" in self.config.ai_model.lower():
                import anthropic

                client = anthropic.Anthropic(api_key=api_key)
                response = client.messages.create(
                    model=self.config.ai_model,
                    max_tokens=1800,
                    messages=[{"role": "user", "content": prompt}],
                )
                return "".join(block.text for block in response.content if getattr(block, "type", "") == "text").strip()
            from openai import OpenAI

            client = OpenAI(api_key=api_key)
            response = client.responses.create(model=self.config.ai_model, input=prompt)
            return response.output_text.strip()
        except Exception:
            return None

    def _run_scheduled_payload(self, payload: dict) -> None:
        command = payload.get("command", "")
        if command:
            self.execute(command)

    def _record_automation(self, context: ExecutionContext) -> str:
        if context.dry_run:
            return "Dry run: I would record keyboard and mouse actions for 30 seconds and save them as a reusable script."
        from pynput import keyboard, mouse

        events: list[tuple[float, str]] = []
        start = time.time()

        def on_press(key) -> None:
            events.append((time.time() - start, f"keyboard.press({repr(getattr(key, 'char', str(key)))})"))

        def on_click(x, y, button, pressed) -> None:
            state = "press" if pressed else "release"
            events.append((time.time() - start, f"mouse.{state}({x}, {y}, {repr(str(button))})"))

        k_listener = keyboard.Listener(on_press=on_press)
        m_listener = mouse.Listener(on_click=on_click)
        k_listener.start()
        m_listener.start()
        time.sleep(30)
        k_listener.stop()
        m_listener.stop()
        lines = [
            "import time",
            "import pyautogui",
            "from pynput.keyboard import Controller as KeyboardController",
            "",
            "keyboard = KeyboardController()",
            "",
        ]
        previous = 0.0
        for event_time, code in events:
            delta = max(0.0, event_time - previous)
            lines.append(f"time.sleep({delta:.3f})")
            if code.startswith("keyboard.press"):
                key_repr = code.split("(", 1)[1].rstrip(")")
                lines.append(f"keyboard.type({key_repr})")
            elif "mouse.press" in code:
                parts = code.split("(")[1].rstrip(")").split(", ")
                lines.append(f"pyautogui.mouseDown({parts[0]}, {parts[1]})")
            elif "mouse.release" in code:
                parts = code.split("(")[1].rstrip(")").split(", ")
                lines.append(f"pyautogui.mouseUp({parts[0]}, {parts[1]})")
            previous = event_time
        script_path = SCRIPTS_DIR / f"automation_{int(start)}.py"
        self.files.create_file(script_path, "\n".join(lines) + "\n")
        return f"Saved automation script to {script_path}."

    def update_config(self, updates: dict[str, Any]) -> str:
        """Modify the persistent config file."""

        for key, value in updates.items():
            if key == "confirm" and isinstance(value, dict):
                for confirm_key, confirm_value in value.items():
                    setattr(self.config.confirm, confirm_key, confirm_value)
            else:
                setattr(self.config, key, value)
        self.config_manager.save(self.config)
        self._apply_runtime_config()
        return f"Updated config: {', '.join(updates.keys())}."

    def generate_script(self, description: str, filename: str, execute_now: bool = True) -> str:
        """Generate and optionally execute a reusable Python script."""

        prompt = (
            "Write a complete Python 3.11 script for this task. Return code only.\nTask: "
            + description
        )
        script = self._ai_text(prompt)
        if not script:
            raise RuntimeError("An AI API key is required to generate a brand-new script.")
        path = SCRIPTS_DIR / filename
        self.files.create_file(path, script)
        if execute_now:
            subprocess.run(["python3", str(path)], check=False)
        return f"Saved script to {path}."

    def _send_hotkey(self, keys: list[str]) -> str:
        import pyautogui

        pyautogui.hotkey(*keys)
        return f"Sent hotkey: {'+'.join(keys)}."

    def _press_hotkey_phrase(self, phrase: str, context: ExecutionContext) -> str:
        keys = [part.strip().lower() for part in phrase.replace("+", " ").split() if part.strip()]
        mapped = [self._normalize_key(key) for key in keys]
        if context.dry_run:
            return f"Dry run: I would send hotkey {'+'.join(mapped)}."
        return self._send_hotkey(mapped)

    def run_voice_loop(self) -> None:
        """Start the wake-word loop and stay alive."""

        self.announce(f"Listening for {self.config.wake_word}.", speak=True)
        stop_event = threading.Event()

        def callback(command: str) -> None:
            result = self.execute(command)
            self.announce(result, speak=True)

        self.voice.wait_for_wake_word(callback, stop_event=stop_event)
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            stop_event.set()

    def _open_spotify_and_search(self, context: ExecutionContext) -> str:
        if context.dry_run:
            return "Dry run: I would open Spotify, search for lo-fi beats, and play the first result."
        self.apps.open_app("Spotify")
        time.sleep(3)
        self._send_hotkey([self._primary_modifier(), "l"])
        self.typing.type_text("lo-fi beats")
        self._send_hotkey(["enter"])
        time.sleep(2)
        self._send_hotkey(["tab"])
        self._send_hotkey(["enter"])
        return "Opened Spotify, searched for lo-fi beats, and started the first result."

    def _open_calendar(self, context: ExecutionContext) -> str:
        if context.dry_run:
            return "Dry run: I would open the calendar app."
        for app_name in ("Calendar", "Google Calendar"):
            try:
                return self.apps.open_app(app_name)
            except Exception:
                continue
        raise RuntimeError("Unable to open a calendar application.")

    def _execute_via_ai_or_fallback(self, command: str, context: ExecutionContext) -> str:
        """Try an AI-generated plan or provide a helpful fallback."""

        if context.dry_run:
            return f"Dry run: I would plan and execute '{command}'. Estimated risk: medium. Estimated time: 30-90 seconds."
        prompt = (
            "You are Zeph, a calm desktop assistant. "
            "The user asked you to perform an action on their computer, but there is no exact built-in flow for it yet. "
            "Reply directly to the user in 2-4 sentences. "
            "Do not mention code, routers, or internal implementation. "
            "Briefly acknowledge the request, state that you do not have that exact action wired up yet, "
            "and suggest one or two more specific next commands Zeph can likely handle.\n\n"
            f"User request: {command}"
        )
        ai_text = self._ai_text(prompt)
        if ai_text:
            return ai_text
        return (
            "I can help with that, but I do not have that exact desktop action wired up yet. "
            "Try breaking it into a more specific step, like opening an app, showing your windows, "
            "taking a screenshot, typing text, or managing a process."
        )

    def _apply_runtime_config(self) -> None:
        """Refresh live modules after config changes."""

        self.typing.set_profile(self._typing_profile())
        self.mouse.speed_multiplier = self.config.speed_multiplier
        self.clipboard.limit = self.config.clipboard_history_limit
        self.voice.wake_word = self.config.wake_word.lower()
        self.voice.language = self.config.voice_language
        self.voice.tts.setProperty("rate", self.config.voice_rate)

    def _extract_scheduled_command(self, command: str) -> str:
        if "," in command:
            return command.split(",", 1)[1].strip()
        if " to " in command.lower():
            return command.split(" to ", 1)[1].strip()
        return command

    def _list_schedules(self) -> str:
        tasks = self.scheduler.list_tasks()
        if not tasks:
            return "No scheduled tasks."
        return "\n".join(
            f"{task.task_id} | {'active' if task.active else 'paused'} | {task.natural_language}"
            for task in tasks
        )

    def _focus_window(self, title: str) -> str:
        self.windows.focus(title)
        return f"Focused window matching '{title}'."

    def _close_app(self, app_name: str, context: ExecutionContext) -> str:
        if context.dry_run:
            return f"Dry run: I would close {app_name}."
        if self.config.confirm.close_window and not self._confirm(f"close {app_name}"):
            return "Close aborted."
        count = self.apps.close_app(app_name, force=False)
        return f"Closed {count} process(es) for {app_name}."

    def _open_url(self, url: str) -> str:
        self.browser.open_default(url)
        return f"Opened {url} in the default browser."

    def _extract_web_text(self, url: str) -> str:
        self.browser.open_url(url, headless=True)
        text = self.browser.extract_text()
        return text[:3000]

    def _format_process_table(self) -> str:
        processes = self.apps.list_processes()[:15]
        if not processes:
            return "No processes available."
        return "\n".join(
            f"PID {proc['pid']} | {proc['name']} | CPU {proc['cpu_percent']}% | RAM {proc['memory_percent']}%"
            for proc in processes
        )

    @staticmethod
    def _primary_modifier() -> str:
        return "command" if platform.system() == "Darwin" else "ctrl"

    def _normalize_key(self, key: str) -> str:
        mapping = {
            "cmd": "command",
            "command": "command",
            "control": "ctrl",
            "option": "alt",
            "return": "enter",
        }
        return mapping.get(key, key)
