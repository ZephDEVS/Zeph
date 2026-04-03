"""Persistent background scheduling."""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Callable

import schedule

from daia.memory import MemoryStore


@dataclass(slots=True)
class ScheduledTask:
    """Normalized task scheduling data."""

    task_id: str
    natural_language: str
    schedule_type: str
    schedule_value: str
    payload: dict
    active: bool = True


class SchedulerService:
    """Runs persistent scheduled tasks in the background."""

    def __init__(self, memory: MemoryStore, callback: Callable[[dict], None]) -> None:
        self.memory = memory
        self.callback = callback
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the scheduler loop and restore saved tasks."""

        self.restore_tasks()
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the scheduler loop."""

        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            schedule.run_pending()
            time.sleep(1)

    def _schedule_job(self, task: ScheduledTask) -> None:
        def run_payload() -> None:
            self.callback(task.payload)

        job = None
        if task.schedule_type == "daily":
            job = schedule.every().day.at(task.schedule_value).do(run_payload)
        elif task.schedule_type == "weekly":
            day_name, time_value = task.schedule_value.split("@", 1)
            job = getattr(schedule.every(), day_name).at(time_value).do(run_payload)
        elif task.schedule_type == "hourly":
            interval = int(task.schedule_value)
            job = schedule.every(interval).hours.do(run_payload)
        if job is not None:
            job.tag(task.task_id)

    def parse_natural_language(self, text: str, payload: dict) -> ScheduledTask:
        """Parse a small set of natural-language scheduling patterns."""

        task_id = str(uuid.uuid4())
        lowered = text.lower()
        daily_match = re.search(r"every day at (\d{1,2}:\d{2}(?:am|pm)?)", lowered)
        weekday_match = re.search(
            r"every (monday|tuesday|wednesday|thursday|friday|saturday|sunday) at (\d{1,2}(?::\d{2})?(?:am|pm)?)",
            lowered,
        )
        hourly_match = re.search(r"every (\d+) hour", lowered)
        if daily_match:
            return ScheduledTask(task_id, text, "daily", self._normalize_time(daily_match.group(1)), payload)
        if weekday_match:
            day = weekday_match.group(1)
            when = self._normalize_time(weekday_match.group(2))
            return ScheduledTask(task_id, text, "weekly", f"{day}@{when}", payload)
        if hourly_match:
            return ScheduledTask(task_id, text, "hourly", hourly_match.group(1), payload)
        raise ValueError("I could not parse that schedule. Try formats like 'every day at 8am' or 'every Monday at 9am'.")

    @staticmethod
    def _normalize_time(raw: str) -> str:
        value = raw.strip().lower()
        if ":" not in value:
            value = value.replace("am", ":00am").replace("pm", ":00pm")
        return time.strftime("%H:%M", time.strptime(value, "%I:%M%p"))

    def add_task(self, natural_language: str, payload: dict) -> ScheduledTask:
        """Create, persist, and schedule a new task."""

        task = self.parse_natural_language(natural_language, payload)
        self.memory.save_schedule(
            task.task_id,
            task.natural_language,
            task.schedule_type,
            task.schedule_value,
            task.payload,
            active=True,
        )
        self._schedule_job(task)
        return task

    def list_tasks(self) -> list[ScheduledTask]:
        """Return persisted schedules."""

        tasks = []
        for row in self.memory.list_schedules():
            tasks.append(
                ScheduledTask(
                    task_id=row.task_id,
                    natural_language=row.natural_language,
                    schedule_type=row.schedule_type,
                    schedule_value=row.schedule_value,
                    payload=json.loads(row.payload),
                    active=row.active,
                )
            )
        return tasks

    def pause_task(self, task_id: str) -> None:
        schedule.clear(task_id)
        self.memory.set_schedule_active(task_id, False)

    def resume_task(self, task_id: str) -> None:
        for task in self.list_tasks():
            if task.task_id == task_id:
                self._schedule_job(task)
                self.memory.set_schedule_active(task_id, True)
                return
        raise ValueError(f"No schedule found for {task_id}.")

    def delete_task(self, task_id: str) -> None:
        schedule.clear(task_id)
        self.memory.delete_schedule(task_id)

    def restore_tasks(self) -> None:
        for task in self.list_tasks():
            if task.active:
                self._schedule_job(task)
