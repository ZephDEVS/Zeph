"""Local web UI launcher and API server for Zeph."""

from __future__ import annotations

import json
import mimetypes
import secrets
import sys
import threading
import time
import webbrowser
from dataclasses import asdict, dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from daia.agent import ZephAgent
from daia.config import AgentConfig
from daia.memory import ConversationMessageRecord, ConversationRecord, UserRecord
from daia.modules.scheduler import ScheduledTask


def _runtime_root() -> Path:
    """Return the directory that contains bundled resources."""

    if hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent.parent


RUNTIME_ROOT = _runtime_root()
FRONTEND_DIST_DIR = RUNTIME_ROOT / "frontend" / "dist"
ASSETS_DIR = RUNTIME_ROOT / "daia" / "assets"
TOS_VERSION = "1.0"


@dataclass(slots=True)
class SessionRecord:
    """Represents an authenticated local web session."""

    token: str
    user: UserRecord
    created_at: float


@dataclass(slots=True)
class PendingPrompt:
    """Represents a blocked agent confirmation or plan approval."""

    prompt_id: int
    prompt_type: str
    title: str
    body: str
    steps: list[str]
    event: threading.Event
    approved: bool | None = None


class ZephWebApp:
    """Owns local web state, the agent instance, and API helpers."""

    def __init__(self) -> None:
        self.agent = ZephAgent(
            event_callback=self._handle_agent_event,
            confirm_handler=self._confirm_from_worker,
            plan_handler=self._approve_plan_from_worker,
        )
        self.memory = self.agent.memory
        self.logger = self.agent.logger
        self.tos_text = (ASSETS_DIR / "tos.txt").read_text(encoding="utf-8")
        self.guide_text = (ASSETS_DIR / "user_guide.md").read_text(encoding="utf-8")
        self._lock = threading.RLock()
        self._events: list[dict[str, Any]] = []
        self._next_event_id = 1
        self._next_prompt_id = 1
        self._sessions: dict[str, SessionRecord] = {}
        self._pending_prompts: dict[int, PendingPrompt] = {}
        self._busy = False
        self._busy_label = "Ready"
        self._active_conversation_id: int | None = None

    def _serialize_config(self) -> dict[str, Any]:
        config = self.agent.config
        return {
            "agentName": config.agent_name,
            "userName": config.user_name,
            "aiProvider": config.ai_provider,
            "aiModel": config.ai_model,
            "browserMode": config.browser_mode,
            "preferredWpm": config.preferred_wpm,
            "wakeWord": config.wake_word,
            "voiceRate": config.voice_rate,
            "voiceLanguage": config.voice_language,
            "speedMode": config.speed_mode,
            "speedMultiplier": config.speed_multiplier,
            "clipboardHistoryLimit": config.clipboard_history_limit,
            "confirm": asdict(config.confirm),
        }

    @staticmethod
    def _serialize_user(user: UserRecord) -> dict[str, Any]:
        return {
            "id": user.user_id,
            "username": user.username,
            "displayName": user.display_name,
            "createdAt": user.created_at,
        }

    @staticmethod
    def _serialize_conversation(conversation: ConversationRecord) -> dict[str, Any]:
        return {
            "id": conversation.conversation_id,
            "title": conversation.title,
            "createdAt": conversation.created_at,
            "updatedAt": conversation.updated_at,
        }

    @staticmethod
    def _serialize_message(message: ConversationMessageRecord) -> dict[str, Any]:
        return {
            "id": message.message_id,
            "conversationId": message.conversation_id,
            "role": message.role,
            "content": message.content,
            "createdAt": message.created_at,
        }

    @staticmethod
    def _serialize_schedule(schedule: ScheduledTask) -> dict[str, Any]:
        return {
            "id": schedule.task_id,
            "naturalLanguage": schedule.natural_language,
            "active": schedule.active,
            "createdAt": getattr(schedule, "created_at", ""),
        }

    def _queue_event(self, event_type: str, payload: dict[str, Any]) -> None:
        with self._lock:
            event = {"id": self._next_event_id, "type": event_type, **payload}
            self._next_event_id += 1
            self._events.append(event)
            if len(self._events) > 500:
                self._events = self._events[-500:]

    def poll_events(self, cursor: int) -> dict[str, Any]:
        with self._lock:
            events = [event for event in self._events if int(event["id"]) > cursor]
            next_cursor = self._events[-1]["id"] if self._events else cursor
            return {
                "events": events,
                "cursor": next_cursor,
                "busy": self._busy,
                "busyLabel": self._busy_label,
            }

    def _set_busy(self, busy: bool, label: str) -> None:
        with self._lock:
            self._busy = busy
            self._busy_label = label
        self._queue_event("status", {"busy": busy, "label": label})

    def _handle_agent_event(self, event_type: str, payload: dict[str, Any]) -> None:
        if event_type == "announce":
            conversation_id = self._active_conversation_id
            if conversation_id is not None:
                message = self.memory.add_conversation_message(conversation_id, "agent", payload["text"])
                self._queue_event("conversation_message", {"message": self._serialize_message(message)})
            return
        if event_type == "plan":
            conversation_id = self._active_conversation_id
            if conversation_id is not None:
                plan_text = "\n".join(f"{idx}. {step}" for idx, step in enumerate(payload["steps"], start=1))
                message = self.memory.add_conversation_message(conversation_id, "plan", plan_text)
                self._queue_event("conversation_message", {"message": self._serialize_message(message)})
            return
        if event_type == "command_started":
            self._set_busy(True, "Working")
            return
        if event_type in {"command_finished", "command_failed"}:
            self._set_busy(False, "Ready")
            return

    def _confirm_from_worker(self, prompt: str) -> bool:
        pending = PendingPrompt(
            prompt_id=self._next_prompt_id,
            prompt_type="confirm",
            title="Confirm action",
            body=f"I'm about to {prompt}. Proceed?",
            steps=[],
            event=threading.Event(),
        )
        with self._lock:
            self._next_prompt_id += 1
            self._pending_prompts[pending.prompt_id] = pending
        self._queue_event(
            "pending_prompt",
            {
                "prompt": {
                    "id": pending.prompt_id,
                    "type": pending.prompt_type,
                    "title": pending.title,
                    "body": pending.body,
                    "steps": pending.steps,
                }
            },
        )
        pending.event.wait(timeout=15)
        with self._lock:
            self._pending_prompts.pop(pending.prompt_id, None)
        return bool(pending.approved)

    def _approve_plan_from_worker(self, steps: list[str]) -> bool:
        pending = PendingPrompt(
            prompt_id=self._next_prompt_id,
            prompt_type="plan",
            title="Approve plan",
            body="Zeph wants your approval before continuing.",
            steps=steps,
            event=threading.Event(),
        )
        with self._lock:
            self._next_prompt_id += 1
            self._pending_prompts[pending.prompt_id] = pending
        self._queue_event(
            "pending_prompt",
            {
                "prompt": {
                    "id": pending.prompt_id,
                    "type": pending.prompt_type,
                    "title": pending.title,
                    "body": pending.body,
                    "steps": pending.steps,
                }
            },
        )
        pending.event.wait(timeout=300)
        with self._lock:
            self._pending_prompts.pop(pending.prompt_id, None)
        return bool(pending.approved)

    def respond_to_prompt(self, prompt_id: int, approved: bool) -> None:
        with self._lock:
            pending = self._pending_prompts.get(prompt_id)
        if pending is None:
            raise ValueError("That prompt is no longer pending.")
        pending.approved = approved
        pending.event.set()

    def bootstrap_payload(self) -> dict[str, Any]:
        return {
            "appName": self.agent.config.agent_name,
            "guide": self.guide_text,
            "tos": self.tos_text,
            "tosVersion": TOS_VERSION,
        }

    def create_session(self, user: UserRecord) -> dict[str, Any]:
        token = secrets.token_urlsafe(24)
        session = SessionRecord(token=token, user=user, created_at=time.time())
        with self._lock:
            self._sessions[token] = session
        self.agent.update_config({"user_name": user.display_name})
        return {
            "token": token,
            "user": self._serialize_user(user),
            "config": self._serialize_config(),
            "tosAccepted": self.memory.has_tos_acceptance(user.user_id, TOS_VERSION),
        }

    def get_session(self, token: str | None) -> SessionRecord:
        if not token:
            raise PermissionError("Authentication required.")
        with self._lock:
            session = self._sessions.get(token)
        if session is None:
            raise PermissionError("Authentication required.")
        return session

    def clear_session(self, token: str | None) -> None:
        if not token:
            return
        with self._lock:
            self._sessions.pop(token, None)

    def login(self, username: str, password: str) -> dict[str, Any]:
        user = self.memory.authenticate_user(username, password)
        if user is None:
            raise ValueError("That username and password combination was not recognized.")
        return self.create_session(user)

    def signup(
        self,
        *,
        username: str,
        display_name: str,
        password: str,
        accept_tos: bool,
        api_key: str,
        preferred_wpm: int,
        wake_word: str,
    ) -> dict[str, Any]:
        if not accept_tos:
            raise ValueError("You need to accept the Terms of Service to create an account.")
        user = self.memory.create_user(username, display_name, password)
        self.memory.accept_tos(user.user_id, TOS_VERSION)
        self.agent.update_config(
            {
                "user_name": user.display_name,
                "api_key": api_key.strip(),
                "preferred_wpm": preferred_wpm,
                "wake_word": wake_word.strip() or "Hey DAIA",
            }
        )
        return self.create_session(user)

    def accept_tos(self, session: SessionRecord) -> dict[str, Any]:
        self.memory.accept_tos(session.user.user_id, TOS_VERSION)
        return {"ok": True}

    def list_conversations(self, session: SessionRecord) -> list[dict[str, Any]]:
        conversations = self.memory.list_conversations(session.user.user_id)
        return [self._serialize_conversation(conversation) for conversation in conversations]

    def _conversation_belongs_to_user(self, user: UserRecord, conversation_id: int) -> bool:
        conversations = self.memory.list_conversations(user.user_id)
        return any(conversation.conversation_id == conversation_id for conversation in conversations)

    def create_conversation(self, session: SessionRecord) -> dict[str, Any]:
        conversation = self.memory.create_conversation(session.user.user_id, "New chat")
        opener = self.memory.add_conversation_message(conversation.conversation_id, "agent", "What can I help you with today?")
        return {
            "conversation": self._serialize_conversation(conversation),
            "messages": [self._serialize_message(opener)],
        }

    def list_messages(self, session: SessionRecord, conversation_id: int) -> list[dict[str, Any]]:
        if not self._conversation_belongs_to_user(session.user, conversation_id):
            raise PermissionError("Conversation not found.")
        messages = self.memory.list_conversation_messages(conversation_id)
        return [self._serialize_message(message) for message in messages]

    def delete_conversation(self, session: SessionRecord, conversation_id: int) -> None:
        if not self._conversation_belongs_to_user(session.user, conversation_id):
            raise PermissionError("Conversation not found.")
        self.memory.delete_conversation(conversation_id)

    def submit_command(self, session: SessionRecord, conversation_id: int, command: str, dry_run: bool) -> dict[str, Any]:
        if not self._conversation_belongs_to_user(session.user, conversation_id):
            raise PermissionError("Conversation not found.")
        with self._lock:
            if self._busy:
                raise RuntimeError("Zeph is already working on another request.")

        rendered = f"dry run: {command}" if dry_run else command
        user_message = self.memory.add_conversation_message(conversation_id, "user", rendered)
        self._retitle_if_needed(session.user, conversation_id, rendered)
        self._queue_event("conversation_message", {"message": self._serialize_message(user_message)})
        self._queue_event("conversation_refresh", {"conversationId": conversation_id})
        self._set_busy(True, "Working")

        worker = threading.Thread(
            target=self._run_command_worker,
            args=(conversation_id, rendered),
            daemon=True,
        )
        worker.start()
        return {"accepted": True, "message": self._serialize_message(user_message)}

    def _retitle_if_needed(self, user: UserRecord, conversation_id: int, command: str) -> None:
        current = next(
            (conversation for conversation in self.memory.list_conversations(user.user_id) if conversation.conversation_id == conversation_id),
            None,
        )
        if current is None or current.title != "New chat":
            return
        title = command.strip()
        if title.lower().startswith("dry run:"):
            title = title.split(":", 1)[1].strip()
        title = title.replace("\n", " ")[:56] or "New chat"
        self.memory.update_conversation_title(conversation_id, title)
        self._queue_event("conversation_refresh", {"conversationId": conversation_id})

    def _run_command_worker(self, conversation_id: int, command: str) -> None:
        self._active_conversation_id = conversation_id
        try:
            result = self.agent.execute(command)
            message = self.memory.add_conversation_message(conversation_id, "agent", result)
            self._queue_event("conversation_message", {"message": self._serialize_message(message)})
        except Exception as exc:
            message = self.memory.add_conversation_message(conversation_id, "error", f"Unhandled failure: {exc}")
            self._queue_event("conversation_message", {"message": self._serialize_message(message)})
        finally:
            self._active_conversation_id = None
            self._set_busy(False, "Ready")
            self._queue_event("conversation_refresh", {"conversationId": conversation_id})

    def list_activity(self) -> dict[str, Any]:
        return {
            "tasks": [
                {
                    "task": str(row["task"]),
                    "status": str(row["status"]),
                    "detail": str(row["detail"]),
                    "createdAt": str(row["created_at"]),
                }
                for row in self.memory.recent_tasks(limit=20)
            ],
            "logs": self.logger.recent_entries(120),
        }

    def list_schedules(self) -> list[dict[str, Any]]:
        return [self._serialize_schedule(schedule) for schedule in self.agent.scheduler.list_tasks()]

    def create_schedule(self, command: str) -> dict[str, Any]:
        task = self.agent.scheduler.add_task(command, {"command": self.agent._extract_scheduled_command(command)})
        self._queue_event("schedule_refresh", {})
        return {"schedule": self._serialize_schedule(task)}

    def mutate_schedule(self, task_id: str, action: str) -> None:
        if action == "pause":
            self.agent.scheduler.pause_task(task_id)
        elif action == "resume":
            self.agent.scheduler.resume_task(task_id)
        elif action == "delete":
            self.agent.scheduler.delete_task(task_id)
        else:
            raise ValueError("Unsupported schedule action.")
        self._queue_event("schedule_refresh", {})

    def settings_payload(self) -> dict[str, Any]:
        return self._serialize_config()

    def update_settings(self, updates: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        int_fields = {"preferredWpm": "preferred_wpm", "voiceRate": "voice_rate", "clipboardHistoryLimit": "clipboard_history_limit"}
        str_fields = {
            "userName": "user_name",
            "aiProvider": "ai_provider",
            "aiModel": "ai_model",
            "browserMode": "browser_mode",
            "apiKey": "api_key",
            "wakeWord": "wake_word",
            "voiceLanguage": "voice_language",
            "speedMode": "speed_mode",
        }
        for source, target in str_fields.items():
            if source in updates:
                normalized[target] = str(updates[source]).strip()
        for source, target in int_fields.items():
            if source in updates:
                normalized[target] = int(updates[source])
        if "confirm" in updates and isinstance(updates["confirm"], dict):
            normalized["confirm"] = updates["confirm"]
        if "speed_mode" in normalized:
            normalized["speed_multiplier"] = ZephAgent.SPEED_MAP.get(normalized["speed_mode"], 1.0)
        self.agent.update_config(normalized)
        self._queue_event("settings_refresh", {"config": self._serialize_config()})
        return self._serialize_config()

    def shutdown(self) -> None:
        try:
            self.agent.browser.close()
        except Exception:
            pass
        try:
            self.agent.scheduler.stop()
        except Exception:
            pass


class ZephRequestHandler(BaseHTTPRequestHandler):
    """HTTP handler for the Zeph local web app."""

    server_version = "ZephWeb/1.0"

    @property
    def app(self) -> ZephWebApp:
        return self.server.app  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self._handle_api_get(parsed)
            return
        self._serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        self._handle_api_post(parsed)

    def do_PUT(self) -> None:
        parsed = urlparse(self.path)
        self._handle_api_put(parsed)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        self._handle_api_delete(parsed)

    def _parse_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _session_token(self) -> str | None:
        header = self.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            return header.split(" ", 1)[1].strip()
        return self.headers.get("X-Session-Token")

    def _require_session(self) -> SessionRecord:
        return self.app.get_session(self._session_token())

    def _send_json(self, payload: dict[str, Any], status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, status: int, message: str) -> None:
        self._send_json({"error": message}, status=status)

    def _handle_api_get(self, parsed: Any) -> None:
        try:
            if parsed.path == "/api/bootstrap":
                self._send_json(self.app.bootstrap_payload())
                return
            if parsed.path == "/api/me":
                session = self._require_session()
                self._send_json(
                    {
                        "user": self.app._serialize_user(session.user),
                        "config": self.app.settings_payload(),
                        "tosAccepted": self.app.memory.has_tos_acceptance(session.user.user_id, TOS_VERSION),
                    }
                )
                return
            if parsed.path == "/api/conversations":
                session = self._require_session()
                self._send_json({"conversations": self.app.list_conversations(session)})
                return
            if parsed.path.startswith("/api/conversations/") and parsed.path.endswith("/messages"):
                session = self._require_session()
                conversation_id = int(parsed.path.split("/")[3])
                self._send_json({"messages": self.app.list_messages(session, conversation_id)})
                return
            if parsed.path == "/api/events":
                self._require_session()
                cursor = int(parse_qs(parsed.query).get("cursor", ["0"])[0])
                self._send_json(self.app.poll_events(cursor))
                return
            if parsed.path == "/api/activity":
                self._require_session()
                self._send_json(self.app.list_activity())
                return
            if parsed.path == "/api/schedules":
                self._require_session()
                self._send_json({"schedules": self.app.list_schedules()})
                return
            if parsed.path == "/api/settings":
                self._require_session()
                self._send_json({"config": self.app.settings_payload()})
                return
            self._send_error_json(HTTPStatus.NOT_FOUND, "Not found.")
        except PermissionError as exc:
            self._send_error_json(HTTPStatus.UNAUTHORIZED, str(exc))
        except ValueError as exc:
            self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def _handle_api_post(self, parsed: Any) -> None:
        try:
            payload = self._parse_json()
            if parsed.path == "/api/auth/login":
                self._send_json(self.app.login(payload.get("username", ""), payload.get("password", "")))
                return
            if parsed.path == "/api/auth/signup":
                self._send_json(
                    self.app.signup(
                        username=payload.get("username", ""),
                        display_name=payload.get("displayName", ""),
                        password=payload.get("password", ""),
                        accept_tos=bool(payload.get("acceptTos")),
                        api_key=payload.get("apiKey", ""),
                        preferred_wpm=int(payload.get("preferredWpm", 80)),
                        wake_word=payload.get("wakeWord", "Hey DAIA"),
                    ),
                    status=HTTPStatus.CREATED,
                )
                return
            if parsed.path == "/api/auth/accept-tos":
                session = self._require_session()
                self._send_json(self.app.accept_tos(session))
                return
            if parsed.path == "/api/auth/logout":
                self.app.clear_session(self._session_token())
                self._send_json({"ok": True})
                return
            if parsed.path == "/api/conversations":
                session = self._require_session()
                self._send_json(self.app.create_conversation(session), status=HTTPStatus.CREATED)
                return
            if parsed.path.startswith("/api/conversations/") and parsed.path.endswith("/command"):
                session = self._require_session()
                conversation_id = int(parsed.path.split("/")[3])
                self._send_json(
                    self.app.submit_command(
                        session,
                        conversation_id,
                        str(payload.get("command", "")).strip(),
                        bool(payload.get("dryRun")),
                    ),
                    status=HTTPStatus.ACCEPTED,
                )
                return
            if parsed.path.startswith("/api/prompts/") and parsed.path.endswith("/respond"):
                self._require_session()
                prompt_id = int(parsed.path.split("/")[3])
                self.app.respond_to_prompt(prompt_id, bool(payload.get("approved")))
                self._send_json({"ok": True})
                return
            if parsed.path == "/api/schedules":
                self._require_session()
                self._send_json(self.app.create_schedule(str(payload.get("command", "")).strip()), status=HTTPStatus.CREATED)
                return
            if parsed.path.startswith("/api/schedules/"):
                self._require_session()
                task_id = parsed.path.split("/")[3]
                action = parsed.path.split("/")[4]
                self.app.mutate_schedule(task_id, action)
                self._send_json({"ok": True})
                return
            self._send_error_json(HTTPStatus.NOT_FOUND, "Not found.")
        except PermissionError as exc:
            self._send_error_json(HTTPStatus.UNAUTHORIZED, str(exc))
        except ValueError as exc:
            self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
        except RuntimeError as exc:
            self._send_error_json(HTTPStatus.CONFLICT, str(exc))
        except Exception as exc:
            self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def _handle_api_put(self, parsed: Any) -> None:
        try:
            if parsed.path == "/api/settings":
                self._require_session()
                self._send_json({"config": self.app.update_settings(self._parse_json())})
                return
            self._send_error_json(HTTPStatus.NOT_FOUND, "Not found.")
        except PermissionError as exc:
            self._send_error_json(HTTPStatus.UNAUTHORIZED, str(exc))
        except ValueError as exc:
            self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def _handle_api_delete(self, parsed: Any) -> None:
        try:
            if parsed.path.startswith("/api/conversations/"):
                session = self._require_session()
                conversation_id = int(parsed.path.split("/")[3])
                self.app.delete_conversation(session, conversation_id)
                self._send_json({"ok": True})
                return
            self._send_error_json(HTTPStatus.NOT_FOUND, "Not found.")
        except PermissionError as exc:
            self._send_error_json(HTTPStatus.UNAUTHORIZED, str(exc))
        except ValueError as exc:
            self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def _serve_static(self, path: str) -> None:
        if not FRONTEND_DIST_DIR.exists():
            self._send_error_json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "Frontend build not found. Run npm install && npm run build in the frontend directory.",
            )
            return
        relative = path.lstrip("/") or "index.html"
        target = (FRONTEND_DIST_DIR / relative).resolve()
        if not str(target).startswith(str(FRONTEND_DIST_DIR.resolve())) or not target.exists() or target.is_dir():
            target = FRONTEND_DIST_DIR / "index.html"
        content = target.read_bytes()
        content_type, _ = mimetypes.guess_type(str(target))
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type or "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def launch_gui() -> int:
    """Launch the React-powered local UI in a native desktop window."""

    app = ZephWebApp()
    server = ThreadingHTTPServer(("127.0.0.1", 0), ZephRequestHandler)
    server.app = app  # type: ignore[attr-defined]
    url = f"http://127.0.0.1:{server.server_port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        try:
            import webview
        except Exception:
            webbrowser.open(url, new=2, autoraise=True)
            while thread.is_alive():
                time.sleep(0.5)
        else:
            webview.create_window(
                app.agent.config.agent_name,
                url,
                width=1440,
                height=920,
                min_size=(1100, 760),
                background_color="#0d0f12",
                text_select=True,
            )
            webview.start(debug=False, http_server=False)
    finally:
        try:
            server.shutdown()
        except Exception:
            pass
        server.server_close()
        app.shutdown()
        thread.join(timeout=2)
    return 0
