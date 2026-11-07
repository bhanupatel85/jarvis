"""Bounded background tool plans, with dependencies and recoverable checkpoints.

Only the app supplies handlers. The model supplies data, never executable code.
Cancellation is cooperative: a running legacy tool keeps its slot and resource
locks until it returns. Interrupted work never restarts itself after a crash.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from core.execution import cancel_event
from core.policy import redact, resources_for
from core.storage import atomic_json

TERMINAL = {"completed", "failed", "cancelled", "timed_out", "blocked"}
RETRY_SAFE = {"web_search", "weather_report"}


@dataclass
class Job:
    id: str
    title: str
    tool: str
    args: dict
    dependencies: list[str] = field(default_factory=list)
    priority: int = 5
    timeout: float = 120
    state: str = "queued"
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    result: str = ""
    attempts: int = 0
    max_retries: int = 0


class TaskManager:
    def __init__(self, checkpoint: Path, handler: Callable, validate: Callable,
                 notify: Callable = lambda _: None, concurrency=3, capacity=100,
                 on_change: Callable = lambda _: None):
        self.path = Path(checkpoint)
        self.handler, self.validate, self.notify = handler, validate, notify
        self.on_change = on_change
        self.concurrency = max(1, min(int(concurrency), 4))
        self.capacity = max(1, min(int(capacity), 200))
        self.jobs: dict[str, Job] = {}
        self._events: dict[str, threading.Event] = {}
        self._held: set[str] = set()
        self._active: dict[str, asyncio.Task] = {}
        self._executor = ThreadPoolExecutor(max_workers=self.concurrency, thread_name_prefix="jarvis-task")
        self._wake = asyncio.Event()
        self._runner = None
        self._closing = False
        self._load()

    def _load(self):
        if not self.path.exists():
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if raw.get("version") != 1 or not isinstance(raw.get("jobs"), list):
            raise ValueError("Unsupported task checkpoint; existing file was preserved.")
        for data in raw["jobs"][-self.capacity:]:
            job = Job(**data)
            # No automatic replay of operations whose side effects are unknown.
            if job.state not in TERMINAL:
                job.state = "interrupted"
                job.result = "Interrupted by application exit. Review before explicitly resuming."
            self.jobs[job.id] = job

    def _save(self):
        atomic_json(self.path, {"version": 1, "jobs": [redact(asdict(j)) for j in self.jobs.values()]})
        try:
            self.on_change(self.snapshot())
        except Exception:
            # A closed panel must never invalidate a saved plan.
            pass

    def start(self):
        if self._runner is None:
            self._runner = asyncio.create_task(self._schedule(), name="jarvis-task-scheduler")
            self._runner.add_done_callback(self._scheduler_stopped)

    def _scheduler_stopped(self, task):
        if task.cancelled() or task.exception() is None:
            return
        self._closing = True
        for event in self._events.values():
            event.set()
        try:
            self.notify(redact(f"ERR: Task scheduler stopped safely: {task.exception()}. Review the task checkpoint before continuing."))
        except Exception:
            pass

    @asynccontextmanager
    async def reserve(self, tool):
        """Foreground and background operations share the same resource boundary."""
        resources = set(resources_for(tool))
        while resources & self._held:
            await asyncio.sleep(0.05)
        self._held.update(resources)
        try:
            yield
        finally:
            self._held.difference_update(resources)
            self._wake.set()

    def submit(self, steps: list[dict]) -> list[str]:
        if self._closing:
            raise ValueError("Task engine is shutting down.")
        if not isinstance(steps, list) or not 1 <= len(steps) <= 20:
            raise ValueError("A plan must contain 1 to 20 steps.")
        if any(not isinstance(step, dict) for step in steps):
            raise ValueError("Every plan step must be an object.")
        if len(self.jobs) + len(steps) > self.capacity:
            raise ValueError("Task history is full. Clear finished tasks before submitting more.")
        pending = []
        aliases = {}
        for step in steps:
            label = str(step.get("id", "")).strip()
            if not label or label in aliases:
                raise ValueError("Every step needs a unique id.")
            aliases[label] = uuid.uuid4().hex[:12]
        for step in steps:
            tool, args = str(step.get("tool", "")), step.get("arguments", {})
            if not isinstance(args, dict) or redact(args) != args:
                raise ValueError("Task arguments must be an object without credentials or private keys.")
            self.validate(tool, args)
            deps = step.get("depends_on", [])
            if not isinstance(deps, list) or any(d not in aliases for d in deps):
                raise ValueError("Dependencies must reference ids in this plan.")
            priority, timeout = step.get("priority", 5), step.get("timeout", 120)
            if type(priority) is not int or not 0 <= priority <= 9:
                raise ValueError("Priority must be an integer from 0 (first) to 9.")
            if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 1 <= timeout <= 3600:
                raise ValueError("Task timeout must be from 1 to 3600 seconds.")
            retries = step.get("max_retries", 0)
            if type(retries) is not int or not 0 <= retries <= 2:
                raise ValueError("Retries must be an integer from 0 to 2.")
            if retries and tool not in RETRY_SAFE:
                raise ValueError("Only read-only web search and weather tasks may be retried automatically.")
            pending.append(Job(aliases[step["id"]], str(step.get("title") or tool)[:160], tool,
                               json.loads(json.dumps(args, allow_nan=False)), [aliases[d] for d in deps], priority, timeout,
                               max_retries=retries))
        # Reject cycles before making any state changes.
        graph = {j.id: j.dependencies for j in pending}
        visiting, visited = set(), set()
        def visit(key):
            if key in visiting:
                raise ValueError("Task dependencies contain a cycle.")
            if key in visited:
                return
            visiting.add(key)
            for dep in graph[key]:
                visit(dep)
            visiting.remove(key)
            visited.add(key)
        for key in graph:
            visit(key)
        for job in pending:
            self.jobs[job.id] = job
        try:
            self._save()  # A plan must be recoverable before executing anything.
        except Exception:
            for job in pending:
                del self.jobs[job.id]
            raise
        self._wake.set()
        return [j.id for j in pending]

    def snapshot(self) -> list[dict]:
        return [redact(asdict(j)) for j in self.jobs.values()]

    def overview(self) -> dict:
        """Compact status without arguments or long/private tool results."""
        counts = dict.fromkeys(('queued','running','paused','interrupted','cancelling','completed','failed','cancelled','timed_out','blocked'), 0)
        active = []
        for job in self.jobs.values():
            counts[job.state] = counts.get(job.state, 0) + 1
            if job.state not in TERMINAL:
                dependencies = [self.jobs[key].title for key in job.dependencies
                                if key in self.jobs and self.jobs[key].state != 'completed']
                active.append({'task_id': job.id, 'title': redact(job.title), 'state': job.state,
                               'waiting_for': [redact(title) for title in dependencies]})
        return {'concurrency': self.concurrency, 'counts': counts, 'active': active,
                'note': 'Independent jobs may overlap; screen input and conflicting file operations are coordinated.'}

    def control(self, action: str, task_id: str = "", priority=5) -> str:
        if action == "clear_finished":
            referenced = {d for j in self.jobs.values() if j.state not in TERMINAL for d in j.dependencies}
            self.jobs = {k: j for k, j in self.jobs.items() if j.state not in TERMINAL or k in referenced}
        else:
            selected = list(self.jobs.values()) if action == "cancel_all" else [self.jobs[task_id]]
            if action not in {"cancel", "cancel_all", "pause", "resume", "prioritize"}:
                raise ValueError("Unknown task action.")
            for job in selected:
                if action in {"cancel", "cancel_all"} and job.state not in TERMINAL:
                    if job.id in self._active:
                        self._events[job.id].set()
                        job.state = "cancelling"
                        job.result = "Cancellation requested; waiting for the running tool to stop safely."
                    else:
                        job.state, job.finished = "cancelled", time.time()
                elif action == "pause":
                    if job.state != "queued":
                        raise ValueError("Only queued work can be paused. Cancel a running operation to stop it safely.")
                    job.state = "paused"
                elif action == "resume":
                    if job.state not in {"paused", "interrupted"}:
                        raise ValueError("Only paused or interrupted work can be resumed.")
                    self.validate(job.tool, job.args)
                    job.state, job.result = "queued", ""
                elif action == "prioritize":
                    if type(priority) is not int or not 0 <= priority <= 9:
                        raise ValueError("Priority must be an integer from 0 to 9.")
                    job.priority = priority
        self._save()
        self._wake.set()
        return "Task state updated."

    async def _schedule(self):
        while not self._closing:
            self._wake.clear()
            changed = False
            for job in sorted(self.jobs.values(), key=lambda j: (j.priority, j.created)):
                if job.state != "queued":
                    continue
                deps = [self.jobs.get(d) for d in job.dependencies]
                if any(d is None or d.state in TERMINAL - {"completed"} for d in deps):
                    job.state, job.finished = "blocked", time.time()
                    job.result = "A dependency did not complete; this operation was not started."
                    self._notify(job)
                    changed = True
                    continue
                if any(d.state != "completed" for d in deps):
                    continue
                resources = set(resources_for(job.tool))
                if len(self._active) >= self.concurrency or resources & self._held:
                    continue
                # Persist the running state before handing the job to a worker.
                job.state, job.started = "running", time.time()
                job.attempts += 1
                self._save()
                self._held.update(resources)
                self._events[job.id] = threading.Event()
                self._active[job.id] = asyncio.create_task(self._execute(job, resources))
            if changed:
                self._save()
            await self._wake.wait()

    def _notify(self, job):
        try:
            self.notify(redact(f"TASK: {job.title} [{job.id}] — {job.state}. {job.result[:240]}"))
        except Exception:
            pass

    async def _execute(self, job, resources):
        event = self._events[job.id]
        def invoke():
            token = cancel_event.set(event)
            try:
                self.validate(job.tool, job.args)  # Recheck policy at execution time.
                return self.handler(job.tool, job.args)
            finally:
                cancel_event.reset(token)
        future = asyncio.get_running_loop().run_in_executor(self._executor, invoke)
        deadline = time.monotonic() + job.timeout
        timed_out = False
        try:
            while not future.done():
                if time.monotonic() >= deadline and not timed_out:
                    timed_out = True
                    event.set()
                    job.state = "cancelling"
                    job.result = "Deadline reached; waiting for the tool to stop safely."
                    self._save()
                    self._notify(job)
                await asyncio.wait({future}, timeout=0.05)
            result = str(future.result() or "Tool returned no verification.")
            job.result = redact(result)[:8000]
            if timed_out:
                job.state = "timed_out"
            elif event.is_set():
                job.state = "cancelled"
            elif result.lower().startswith(("status=failed", "tool '", "execution error:",
                                           "search failed", "could not ", "error:", "file controller error")):
                job.state = "failed"
            elif result.startswith("status=unverified") or result.startswith("status=started") or "[CONFIRMATION_PENDING]" in result:
                job.state = "failed"
                job.result = "Operation was not verified complete. " + job.result
            else:
                # 'completed' means the handler returned, not that arbitrary GUI
                # side effects were verified. Preserve the tool's exact evidence.
                job.state = "completed"
        except Exception as exc:
            job.state = "timed_out" if timed_out else "cancelled" if event.is_set() else "failed"
            job.result = redact(f"{type(exc).__name__}: {exc}")[:8000]
        finally:
            if job.state == "failed" and job.tool in RETRY_SAFE and job.attempts <= job.max_retries:
                job.state = "queued"
                job.result = "Previous attempt failed; queued a bounded retry. " + job.result
            else:
                job.finished = time.time()
            self._held.difference_update(resources)
            self._active.pop(job.id, None)
            self._events.pop(job.id, None)
            try:
                self._save()
                self._notify(job)
            finally:
                self._wake.set()

    async def close(self):
        self._closing = True
        self.control("cancel_all")
        self._wake.set()
        if self._runner:
            await self._runner
        # Do not claim that uncooperative legacy threads have stopped.
        if self._active:
            await asyncio.gather(*list(self._active.values()))
        self._executor.shutdown(wait=False)


TASK_TOOL = {
    "name": "task_manager", "tier": "core",
    "description": "Submit a bounded background plan of existing tools. Independent steps run concurrently; use depends_on for ordering. Use overview for a short progress summary without full results. Check status, pause queued work, resume interrupted work, prioritize or cancel. Never claim success before results. High-risk tools need a separate human confirmation and cannot run in background plans.",
    "parameters": {"type": "OBJECT", "properties": {
        "action": {"type": "STRING", "enum": ["submit", "status", "overview", "pause", "resume", "prioritize", "cancel", "cancel_all", "clear_finished"]},
        "task_id": {"type": "STRING"}, "priority": {"type": "INTEGER", "minimum": 0, "maximum": 9},
        "steps": {"type": "ARRAY", "maxItems": 20, "items": {"type": "OBJECT", "properties": {
            "id": {"type": "STRING"}, "title": {"type": "STRING"}, "tool": {"type": "STRING"},
            "arguments_json": {"type": "STRING", "description": "JSON object matching the target tool's parameters"},
            "depends_on": {"type": "ARRAY", "items": {"type": "STRING"}},
            "priority": {"type": "INTEGER"}, "timeout": {"type": "NUMBER"},
            "max_retries": {"type": "INTEGER", "description": "0 to 2; only read-only search/weather can retry"}
        }, "required": ["id", "tool", "arguments_json"]}}
    }, "required": ["action"]}
}
