"""Core agent orchestration, planning, and task routing."""

from __future__ import annotations

import json
import os
import platform
import random
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib import error as urllib_error
from urllib import request as urllib_request

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
        self._migrate_local_ai_defaults()
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
        self._ollama_boot_attempted_at = 0.0
        self._ollama_pull_lock = threading.Lock()
        self._ollama_pull_thread: threading.Thread | None = None
        self._ollama_pull_target = ""
        self._ollama_pull_status = "idle"
        self.scheduler = SchedulerService(self.memory, callback=self._run_scheduled_payload)
        self.scheduler.start()
        self._warm_ai_backend()

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

    def _migrate_local_ai_defaults(self) -> None:
        """Move older cloud-default configs to local-first mode when no key is configured."""

        provider = (self.config.ai_provider or "").strip().lower()
        model = self.config.ai_model.strip().lower()
        has_api_key = bool(self.config.api_key or os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY"))
        if has_api_key:
            return
        if (provider == "anthropic" and model == "claude-sonnet-4-20250514") or (
            provider == "openai" and model == "gpt-5-mini"
        ):
            self.config.ai_provider = "auto"
            self.config.ai_model = "llama3.2:3b"
            self.config_manager.save(self.config)

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

    def _warm_ai_backend(self) -> None:
        """Prepare the preferred local model in the background when appropriate."""

        if (self.config.ai_provider or "auto").strip().lower() in {"auto", "ollama"}:
            self.ensure_ollama_model(background=True)

    def ai_status(self) -> dict[str, Any]:
        """Report which AI backend Zeph can use right now."""

        provider, model, available = self._resolve_ai_backend()
        if self._ollama_pull_status == "downloading" and available and provider == "ollama" and model:
            message = f"Downloading local model {self._ollama_pull_target}. Using {model} for now."
        elif self._ollama_pull_status == "downloading":
            message = f"Downloading local model {self._ollama_pull_target}..."
        elif self._ollama_pull_status == "failed":
            message = f"Could not download local model {self._ollama_pull_target}. Zeph will use another backend or safe fallbacks."
        elif available:
            message = f"{provider} ready with {model}"
        elif self.config.ai_provider == "ollama":
            message = "Ollama is selected, but no local model is available yet."
        elif self.config.ai_provider == "auto":
            message = "No local or cloud AI backend is available. Zeph will use safe fallbacks."
        else:
            message = f"{self.config.ai_provider} is selected, but Zeph cannot reach it right now."
        return {
            "configured_provider": self.config.ai_provider,
            "configured_model": self.config.ai_model,
            "resolved_provider": provider,
            "resolved_model": model,
            "available": available,
            "message": message,
            "pullStatus": self._ollama_pull_status,
            "pullTarget": self._ollama_pull_target,
        }

    @staticmethod
    def _ollama_base_url() -> str:
        host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").strip()
        if host.startswith("http://") or host.startswith("https://"):
            return host.rstrip("/")
        return f"http://{host.rstrip('/')}"

    def _json_request(
        self,
        url: str,
        *,
        payload: dict[str, Any] | None = None,
        timeout: float = 3.0,
    ) -> dict[str, Any]:
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib_request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
        with urllib_request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def _ollama_models(self) -> list[str]:
        try:
            payload = self._json_request(f"{self._ollama_base_url()}/api/tags", timeout=1.5)
        except (urllib_error.URLError, TimeoutError, ValueError, OSError):
            return []
        models = []
        for item in payload.get("models", []):
            name = str(item.get("name", "")).strip()
            if name:
                models.append(name)
        return models

    def _ensure_ollama_server(self) -> list[str]:
        models = self._ollama_models()
        if models:
            return models
        if shutil.which("ollama") is None:
            if platform.system() == "Darwin":
                try:
                    subprocess.Popen(
                        ["open", "-a", "Ollama"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True,
                    )
                except Exception:
                    return []
                for _ in range(12):
                    time.sleep(0.5)
                    if shutil.which("ollama") is not None:
                        break
                    models = self._ollama_models()
                    if models:
                        return models
            if shutil.which("ollama") is None:
                return []
        if time.time() - self._ollama_boot_attempted_at < 15:
            return []
        self._ollama_boot_attempted_at = time.time()
        try:
            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception:
            return []
        for _ in range(8):
            time.sleep(0.5)
            models = self._ollama_models()
            if models:
                return models
        return []

    def _set_ollama_pull_status(self, status: str, target: str = "") -> None:
        self._ollama_pull_status = status
        self._ollama_pull_target = target
        self._emit("settings_changed")

    def _run_ollama_pull(self, model: str) -> None:
        with self._ollama_pull_lock:
            self._set_ollama_pull_status("downloading", model)
            self._emit("announce", text=f"Downloading local model {model}.")
            try:
                self._ensure_ollama_server()
                subprocess.run(
                    ["ollama", "pull", model],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self._set_ollama_pull_status("ready", model)
                self._emit("announce", text=f"Local model {model} is ready.")
            except Exception:
                self._set_ollama_pull_status("failed", model)
                self._emit("announce", text=f"Could not download local model {model}.")
            finally:
                self._ollama_pull_thread = None

    def ensure_ollama_model(self, background: bool = True) -> bool:
        """Ensure the configured Ollama model exists locally, optionally in the background."""

        preferred = self.config.ai_model.strip() or "llama3.2:3b"
        models = self._ensure_ollama_server()
        if preferred in models:
            self._set_ollama_pull_status("ready", preferred)
            return True
        preferred_base = preferred.split(":", 1)[0]
        if any(model.split(":", 1)[0] == preferred_base for model in models):
            chosen = next(model for model in models if model.split(":", 1)[0] == preferred_base)
            self._set_ollama_pull_status("ready", chosen)
            return True
        if shutil.which("ollama") is None:
            self._set_ollama_pull_status("failed", preferred)
            return False
        if self._ollama_pull_thread and self._ollama_pull_thread.is_alive():
            return False
        if background:
            worker = threading.Thread(target=self._run_ollama_pull, args=(preferred,), daemon=True)
            self._ollama_pull_thread = worker
            worker.start()
            return False
        self._run_ollama_pull(preferred)
        return self._ollama_pull_status == "ready"

    def _select_ollama_model(self, models: list[str], allow_fallback: bool = True) -> str | None:
        preferred = self.config.ai_model.strip()
        if preferred in models:
            return preferred
        preferred_base = preferred.split(":", 1)[0] if preferred else ""
        for model in models:
            if preferred_base and model.split(":", 1)[0] == preferred_base:
                return model
        if not allow_fallback:
            return None
        for candidate in ("llama3.2:3b", "llama3.2", "qwen2.5:7b", "qwen2.5", "mistral", "phi4"):
            if candidate in models:
                return candidate
        return models[0] if models else None

    def _resolve_ai_backend(self) -> tuple[str | None, str | None, bool]:
        provider = (self.config.ai_provider or "auto").strip().lower()
        model = self.config.ai_model.strip()

        if provider in {"auto", "ollama"}:
            models = self._ensure_ollama_server()
            preferred_ollama_model = self._select_ollama_model(models, allow_fallback=False)
            if preferred_ollama_model:
                self._set_ollama_pull_status("ready", preferred_ollama_model)
                return "ollama", preferred_ollama_model, True
            fallback_ollama_model = self._select_ollama_model(models, allow_fallback=True)
            if fallback_ollama_model:
                self.ensure_ollama_model(background=True)
                return "ollama", fallback_ollama_model, True
            self.ensure_ollama_model(background=True)
            if provider == "ollama":
                return "ollama", model or None, False

        anthropic_key = self.config.api_key or os.getenv("ANTHROPIC_API_KEY")
        openai_key = self.config.api_key or os.getenv("OPENAI_API_KEY")

        if provider in {"auto", "anthropic"} and anthropic_key:
            selected_model = model if model and "claude" in model.lower() else "claude-sonnet-4-20250514"
            if provider == "anthropic" or ("claude" in selected_model.lower() and not openai_key):
                return "anthropic", selected_model, True

        if provider in {"auto", "openai"} and openai_key:
            selected_model = model if model and "claude" not in model.lower() else "gpt-5-mini"
            if provider == "openai" or provider == "auto":
                return "openai", selected_model, True

        if provider == "anthropic":
            return "anthropic", model or "claude-sonnet-4-20250514", False
        if provider == "openai":
            return "openai", model or "gpt-5-mini", False
        return None, model or None, False

    def first_run_setup(self) -> AgentConfig:
        """Prompt for initial settings and persist them."""

        if self.config_manager.exists():
            return self.config
        self.console.print(Panel.fit("Welcome to Zeph. Let's configure your desktop agent."))
        user_name = input("Your name: ").strip()
        api_key = input("AI API key (optional if you use Ollama locally): ").strip()
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
        prompt = (
            "Break this desktop automation goal into 4-7 concise ordered steps. "
            "Return JSON only as {\"steps\": [\"...\"]}. Goal: "
            + goal
        )
        try:
            text = self._ai_text(prompt=prompt, system_prompt="Return JSON only.", max_tokens=500)
            if not text:
                return None
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
            answer = input(f"I'm about to {prompt} - confirm? (y/n) ").strip().lower()
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
            "go to google",
            "open google",
            "search google",
            "google search",
            "on google",
            "in google",
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

    def _conversation_excerpt(self, conversation_id: int | None, limit: int = 10) -> list[dict[str, str]]:
        """Return recent conversation turns as lightweight chat messages."""

        if conversation_id is None:
            return []
        history = self.memory.list_conversation_messages(conversation_id)
        excerpt: list[dict[str, str]] = []
        role_map = {
            "user": "user",
            "agent": "assistant",
            "plan": "assistant",
            "system": "assistant",
            "error": "assistant",
        }
        for item in history[-limit:]:
            role = role_map.get(item.role)
            if role is None:
                continue
            content = item.content.strip()
            if content:
                excerpt.append({"role": role, "content": content})
        return excerpt

    @staticmethod
    def _stable_pick(options: list[str], seed_text: str) -> str:
        if not options:
            return ""
        index = abs(hash(seed_text)) % len(options)
        return options[index]

    def _fallback_chat_response(self, simple: str, command: str) -> str:
        """Return a richer non-AI fallback when no model is available."""

        options_map = {
            "greeting": [
                "Hi. What are we working on?",
                "Hey. What would you like help with?",
                "Hi there. What do you want to do?",
                "Hey. I'm ready when you are.",
                "Hi. Tell me what you need.",
            ],
            "thanks": [
                "You're welcome.",
                "Anytime.",
                "Happy to help.",
                "Of course.",
                "Glad to help.",
            ],
            "capabilities": [
                "I can chat with you naturally, and I can also act on your computer when you ask. That includes windows, apps, typing, files, the browser, screenshots, and automations.",
                "I can talk things through with you, or I can directly operate your desktop: open apps, type into documents, inspect the screen, manage files, and run workflows.",
                "I work like a normal assistant until you want action. Then I can control windows, browser tasks, typing, screenshots, files, and scheduled automations.",
            ],
            "help": [
                "You can talk to me normally, or ask me to do something directly on your computer. For example: 'show my windows', 'open a Google Doc and type a sentence about the moon', or 'take a screenshot and tell me what you see.'",
                "Ask normally if you want a conversation, or give me a desktop task like opening an app, typing text, checking your screen, or organizing files.",
                "You can treat this like chat, or like an operator. Try something like 'what windows do I have open right now?' or 'sort my Downloads folder.'",
            ],
            "who": [
                "I'm Zeph, your local desktop assistant. I can chat with you normally and also take action on your Mac when you ask.",
                "I'm Zeph. Think of me as a calm assistant that can also operate apps, windows, files, and browser tasks on your computer.",
                "I'm Zeph, a local assistant built for normal conversation plus desktop control.",
            ],
            "question": [
                "I can help with that. If you want, say more about what you need or tell me to take an action on your computer.",
                "I'm with you. Ask it normally, or tell me what you want me to do on your Mac.",
                "I can help. Keep talking it through, or ask me to act directly on your computer.",
            ],
            "default": [
                "I'm here. Tell me what you want to work on.",
                "I'm ready. You can talk normally, or ask me to do something on your computer.",
                "I'm with you. If you want, we can talk it through or turn it into an action.",
                "All set. Tell me what you need.",
            ],
        }

        if simple in {"hi", "hello", "hey"}:
            return self._stable_pick(options_map["greeting"], simple)
        if simple in {"thanks", "thank you"}:
            return self._stable_pick(options_map["thanks"], simple)
        if simple == "who are you":
            return self._stable_pick(options_map["who"], simple)
        if simple in {"what can you do", "what do you do"}:
            return self._stable_pick(options_map["capabilities"], simple)
        if simple == "help":
            return self._stable_pick(options_map["help"], simple)
        if command.strip().endswith("?"):
            return self._stable_pick(options_map["question"], command)
        return self._stable_pick(options_map["default"], command)

    def _respond_as_chat(self, command: str, conversation_id: int | None = None) -> str:
        """Handle ordinary conversation without task-execution framing."""

        lowered = command.strip().lower()
        simple = re.sub(r"[^a-z0-9\s]", "", lowered).strip()

        prompt = (
            "You are Zeph, a calm and capable desktop assistant with a Claude-like tone. "
            "Respond naturally, avoid reusing the same stock lines, and keep replies concise unless depth is needed. "
            "Do not mention internal routing, tools, code, APIs, or implementation details unless the user explicitly asks. "
            "If the user is greeting you, be brief and warm. "
            "If they ask what you can do, explain that you can chat naturally and can also act on their computer when asked. "
            "If the user is frustrated, be steady and practical."
        )
        ai_text = self._ai_text(prompt=command, conversation_id=conversation_id, system_prompt=prompt, max_tokens=900)
        if not ai_text:
            ai_text = self._ai_text(prompt=command, conversation_id=conversation_id, max_tokens=500)
        if ai_text:
            return ai_text
        return self._fallback_chat_response(simple, command)

    def set_speed(self, mode: str) -> str:
        """Update global speed mode."""

        if mode not in self.SPEED_MAP:
            raise ValueError(f"Unsupported speed mode: {mode}")
        self.config.speed_mode = mode
        self.config.speed_multiplier = self.SPEED_MAP[mode]
        self.config_manager.save(self.config)
        self._apply_runtime_config()
        return f"Speed set to {mode} ({self.config.speed_multiplier}x)."

    def execute(self, command: str, conversation_id: int | None = None) -> str:
        """Route and execute a natural-language command."""

        original = command
        command, context = self._context_for_command(command)
        self.logger.log("INPUT", original)
        lowered = command.lower()
        self._emit("command_started", command=original, dry_run=context.dry_run)
        try:
            if not self._is_action_request(command):
                result = self._respond_as_chat(command, conversation_id=conversation_id)
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
            if self._is_google_search_request(lowered):
                return self._handle_google_search_request(command, context)
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
        try:
            stats = self.typing.type_text(text)
            mode = "typed"
        except Exception as exc:
            self.logger.log("SYSTEM", f"Typing simulation failed, falling back to clipboard paste: {exc}")
            stats = self._paste_text_via_clipboard(text)
            mode = "pasted"
        try:
            focused = self.windows.focused_window()
            self.memory.set_behavior(focused, "preferred_wpm", self.config.preferred_wpm)
        except Exception:
            pass
        self.logger.log("SYSTEM", f"{mode.capitalize()} {stats['typed_chars']} characters.")
        if mode == "typed":
            return f"Typed {stats['typed_chars']} characters in {stats['elapsed']} seconds."
        return f"Typing permissions were unreliable, so I pasted {stats['typed_chars']} characters instead."

    def _paste_text_via_clipboard(self, text: str) -> dict[str, int | float]:
        """Paste text through the clipboard as a fallback when keystrokes fail."""

        previous_clipboard = ""
        try:
            previous_clipboard = self.clipboard.read()
        except Exception:
            previous_clipboard = ""
        self.clipboard.write(text)
        time.sleep(0.08)
        self._send_hotkey([self._primary_modifier(), "v"])
        time.sleep(0.08)
        try:
            self.clipboard.write(previous_clipboard)
        except Exception:
            pass
        return {"typed_chars": len(text), "corrections": 0, "elapsed": 0.16}

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
            paste_fallback=self._paste_text_via_clipboard,
            headless=False,
            browser_mode=self.config.browser_mode,
        )
        self.logger.log("WEB", f"Created Google Doc at {result['url']}.")
        if result.get("input_mode") == "pasted":
            return (
                f"Essay complete and verified. I pasted the content because direct typing was unreliable. "
                f"Final word count: {result['word_count']}. Document URL: {result['url']}"
            )
        return f"Essay complete and verified. Final word count: {result['word_count']}. Document URL: {result['url']}"

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
            paste_fallback=self._paste_text_via_clipboard,
            headless=False,
            browser_mode=self.config.browser_mode,
        )
        self.logger.log("WEB", f"Created Google Doc at {result['url']}.")
        if result.get("input_mode") == "pasted":
            return (
                f"Google Doc ready and verified. I pasted {result['word_count']} words because direct typing was unreliable. "
                f"Document URL: {result['url']}"
            )
        return f"Google Doc ready and verified. Typed {result['word_count']} words. Document URL: {result['url']}"

    @staticmethod
    def _is_google_search_request(lowered: str) -> bool:
        if "google doc" in lowered or "google docs" in lowered or "docs.new" in lowered:
            return False
        patterns = (
            "go to google",
            "open google",
            "google and type",
            "google and search",
            "search google",
            "google search",
            " on google",
            " in google",
        )
        return any(pattern in lowered for pattern in patterns)

    def _handle_google_search_request(self, command: str, context: ExecutionContext) -> str:
        query = self._extract_google_search_query(command)
        if context.dry_run:
            if query:
                return f"Dry run: I would open Google and search for: {query}"
            return "Dry run: I would open Google in the default browser."
        self.notifier.notify("Zeph", "Opening Google.", timeout=3)
        if not query:
            self.browser.open_default("https://www.google.com")
            return "Opened Google in the default browser."
        result = self.browser.google_search(
            query,
            self.typing,
            paste_fallback=self._paste_text_via_clipboard,
            headless=False,
            browser_mode=self.config.browser_mode,
        )
        self.logger.log("WEB", f"Opened Google and submitted query: {query}")
        chars = int(result["typing_stats"]["typed_chars"])
        if result["input_mode"] == "typed":
            return f"Opened Google and typed {chars} characters for the search: {query}"
        return f"Opened Google and pasted the search because direct typing was unreliable: {query}"

    def _extract_google_search_query(self, command: str) -> str:
        quoted = re.search(r"""['"]([^'"]+)['"]""", command)
        if quoted:
            return quoted.group(1).strip()

        patterns = (
            r"\b(?:open|go to|goto|launch)\s+google(?:\.com)?\s+(?:and\s+)?(?:type|search(?:\s+for)?)\s+(.+)$",
            r"\bsearch\s+google\s+(?:for\s+)?(.+)$",
            r"\bgoogle\s+search\s+(?:for\s+)?(.+)$",
            r"\b(?:type|search(?:\s+for)?)\s+(.+?)\s+(?:on|in)\s+google(?:\.com)?$",
        )
        for pattern in patterns:
            match = re.search(pattern, command, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip().rstrip(".")
        return ""

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
        ai_text = self._ai_text(prompt=prompt, max_tokens=250)
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
        ai_text = self._ai_text(prompt=prompt, max_tokens=2200)
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

    def _prompt_with_history(self, prompt: str, conversation_id: int | None) -> str:
        excerpt = self._conversation_excerpt(conversation_id)
        if not excerpt:
            return prompt
        lines = ["Recent conversation context:"]
        for item in excerpt:
            speaker = "User" if item["role"] == "user" else "Zeph"
            lines.append(f"{speaker}: {item['content']}")
        lines.append("")
        lines.append(f"Current user message: {prompt}")
        return "\n".join(lines)

    def _ollama_chat(
        self,
        *,
        model: str,
        prompt: str,
        conversation_id: int | None,
        system_prompt: str | None,
        max_tokens: int,
    ) -> str | None:
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.extend(self._conversation_excerpt(conversation_id))
        if not messages or messages[-1]["role"] != "user" or messages[-1]["content"] != prompt:
            messages.append({"role": "user", "content": prompt})
        payload = {
            "model": model,
            "stream": False,
            "messages": messages,
            "options": {
                "temperature": 0.8,
                "num_predict": max_tokens,
            },
        }
        try:
            data = self._json_request(f"{self._ollama_base_url()}/api/chat", payload=payload, timeout=180.0)
        except (urllib_error.URLError, TimeoutError, ValueError, OSError) as exc:
            self.logger.log("AI", f"Ollama chat failed for model {model}: {exc}")
            return None
        message = data.get("message", {})
        return str(message.get("content", "")).strip() or None

    def _anthropic_text(self, *, model: str, prompt: str, system_prompt: str | None, max_tokens: int) -> str | None:
        api_key = self.config.api_key or os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            return None
        try:
            import anthropic

            client = anthropic.Anthropic(api_key=api_key)
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system_prompt or "",
                messages=[{"role": "user", "content": prompt}],
            )
            return "".join(block.text for block in response.content if getattr(block, "type", "") == "text").strip() or None
        except Exception as exc:
            self.logger.log("AI", f"Anthropic chat failed for model {model}: {exc}")
            return None

    def _openai_text(self, *, model: str, prompt: str, system_prompt: str | None, max_tokens: int) -> str | None:
        api_key = self.config.api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            return None
        try:
            from openai import OpenAI

            client = OpenAI(api_key=api_key)
            user_input = prompt if not system_prompt else f"{system_prompt}\n\n{prompt}"
            response = client.responses.create(model=model, input=user_input, max_output_tokens=max_tokens)
            return response.output_text.strip() or None
        except Exception as exc:
            self.logger.log("AI", f"OpenAI chat failed for model {model}: {exc}")
            return None

    def _ai_text(
        self,
        *,
        prompt: str,
        conversation_id: int | None = None,
        system_prompt: str | None = None,
        max_tokens: int = 1800,
    ) -> str | None:
        provider, model, available = self._resolve_ai_backend()
        if not available or not provider or not model:
            self.logger.log("AI", "No AI backend available for this reply; using fallback response.")
            return None
        enriched_prompt = self._prompt_with_history(prompt, conversation_id)
        if provider == "ollama":
            return self._ollama_chat(
                model=model,
                prompt=prompt,
                conversation_id=conversation_id,
                system_prompt=system_prompt,
                max_tokens=max_tokens,
            )
        if provider == "anthropic":
            return self._anthropic_text(
                model=model,
                prompt=enriched_prompt,
                system_prompt=system_prompt,
                max_tokens=max_tokens,
            )
        if provider == "openai":
            return self._openai_text(
                model=model,
                prompt=enriched_prompt,
                system_prompt=system_prompt,
                max_tokens=max_tokens,
            )
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

        should_refresh_ai = any(key in updates for key in ("ai_provider", "ai_model", "api_key"))
        for key, value in updates.items():
            if key == "confirm" and isinstance(value, dict):
                for confirm_key, confirm_value in value.items():
                    setattr(self.config.confirm, confirm_key, confirm_value)
            else:
                setattr(self.config, key, value)
        self.config_manager.save(self.config)
        self._apply_runtime_config()
        if should_refresh_ai:
            self._set_ollama_pull_status("idle", self.config.ai_model.strip())
            self._warm_ai_backend()
        return f"Updated config: {', '.join(updates.keys())}."

    def generate_script(self, description: str, filename: str, execute_now: bool = True) -> str:
        """Generate and optionally execute a reusable Python script."""

        prompt = (
            "Write a complete Python 3.11 script for this task. Return code only.\nTask: "
            + description
        )
        script = self._ai_text(prompt=prompt, max_tokens=2200)
        if not script:
            raise RuntimeError("A reachable AI backend is required to generate a brand-new script.")
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
        ai_text = self._ai_text(prompt=prompt, max_tokens=500)
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
