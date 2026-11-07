"""Bounded, cancellable child processes and contained generated-file paths.

This is process supervision, not a sandbox: approved code has the user's rights.
"""
from __future__ import annotations

import contextvars
import os
import shlex
import signal
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

cancel_event = contextvars.ContextVar("jarvis_cancel_event", default=None)
_slots = threading.BoundedSemaphore(2)
MAX_OUTPUT = 64_000


def check_cancelled():
    event = cancel_event.get()
    if event is not None and event.is_set():
        raise InterruptedError("Task cancelled; no further operations were started.")


def contained_path(root: Path, relative: str) -> Path:
    """Reject absolute paths, traversal, NTFS streams and existing symlink escapes."""
    raw = str(relative)
    win = PureWindowsPath(raw)
    if not raw.strip() or win.is_absolute() or win.drive or win.root or ":" in raw:
        raise ValueError("Generated file must use a relative project path.")
    parts = raw.replace("\\", "/").split("/")
    if any(p == ".." or p.rstrip(" .") != p for p in parts):
        raise ValueError("Generated file path contains traversal or ambiguous components.")
    devices = {"con", "prn", "aux", "nul"} | {f"{prefix}{n}" for prefix in ("com", "lpt") for n in range(1, 10)}
    if any(p.split(".", 1)[0].casefold() in devices for p in parts):
        raise ValueError("Generated file cannot use a reserved Windows device name.")
    base = Path(root).resolve()
    target = base.joinpath(*parts).resolve()
    if target == base or not target.is_relative_to(base):
        raise ValueError("Generated file would escape the project directory.")
    if any(p.casefold() in {".git", ".ssh", ".aws"} for p in parts):
        raise ValueError("Generated code cannot overwrite repository or credential metadata.")
    return target


def command_args(command: str) -> list[str]:
    # Windows shlex retains quotes with posix=False; strip enclosing quotes only.
    parts = shlex.split(command, posix=os.name != "nt")
    if os.name == "nt":
        parts = [p[1:-1] if len(p) > 1 and p[0] == p[-1] == '"' else p for p in parts]
    if not parts:
        raise ValueError("Command cannot be empty.")
    return parts


@dataclass(frozen=True)
class ProcessResult:
    returncode: int | None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    cancelled: bool = False

    def describe(self) -> str:
        status = "cancelled" if self.cancelled else "timed_out" if self.timed_out else (
            "done" if self.returncode == 0 else "failed")
        return (f"status={status} exit_code={self.returncode}\n"
                f"STDOUT:\n{self.stdout}\nSTDERR:\n{self.stderr}")


def _stop_tree(process):
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()
    process.wait(timeout=10)


def run_process(args: list[str], cwd: Path, timeout: float = 30) -> ProcessResult:
    if not isinstance(args, list) or not args or any(not isinstance(a, str) for a in args):
        raise ValueError("Command must be a non-empty list of strings.")
    timeout = max(1.0, min(float(timeout), 300.0))
    deadline = time.monotonic() + timeout
    while not _slots.acquire(timeout=0.05):
        check_cancelled()
        if time.monotonic() >= deadline:
            return ProcessResult(None, stderr="Process capacity was busy.", timed_out=True)
    try:
        check_cancelled()
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            kw = ({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt"
                  else {"start_new_session": True})
            proc = subprocess.Popen(args, cwd=str(cwd), stdin=subprocess.DEVNULL,
                                    stdout=out, stderr=err, shell=False, **kw)
            expired = cancelled = False
            try:
                while proc.poll() is None:
                    event = cancel_event.get()
                    cancelled = bool(event is not None and event.is_set())
                    expired = time.monotonic() >= deadline
                    if cancelled or expired:
                        _stop_tree(proc)
                        break
                    time.sleep(0.05)
            finally:
                if proc.poll() is None:
                    _stop_tree(proc)
            def read(stream):
                stream.seek(0)
                data = stream.read(MAX_OUTPUT + 1)
                return data[:MAX_OUTPUT].decode("utf-8", errors="replace") + (
                    "\n[output truncated]" if len(data) > MAX_OUTPUT else "")
            return ProcessResult(proc.returncode, read(out), read(err), expired, cancelled)
    finally:
        _slots.release()
