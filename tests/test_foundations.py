import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from core import policy
from core.commands import stop_command
from core.execution import contained_path, run_process, cancel_event
from core.storage import atomic_json
from core.tasks import TaskManager
from memory import config_manager as config
from memory import memory_manager as memory


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "settings.json"
        self.patches = [patch.object(config, "CONFIG_FILE", self.path),
                        patch.object(config, "CONFIG_DIR", self.path.parent),
                        patch.object(memory, "MEMORY_PATH", self.path.parent / "memory.json")]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def test_all_settings_transactions_preserve_concurrent_changes(self):
        atomic_json(self.path, {"untouched": "keep"})
        def save(i):
            config.save_plugin_config("suite", {f"field{i}": i})
            config.save_provider_config("local", {f"field{i}": i})
            config._patch_config(**{f"setting{i}": i})
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(save, range(30)))
        data = json.loads(self.path.read_text())
        self.assertEqual(data["untouched"], "keep")
        self.assertEqual(len(data["plugin_config"]["suite"]), 30)
        self.assertEqual(len(data["providers"]["creds"]["local"]), 30)
        self.assertTrue(all(data[f"setting{i}"] == i for i in range(30)))

    def test_corrupt_settings_never_overwritten(self):
        self.path.write_text("{truncated")
        with self.assertRaises(ValueError):
            config.save_voice("Puck")
        self.assertEqual(self.path.read_text(), "{truncated")

    def test_failed_replace_preserves_existing_json_and_cleans_temp(self):
        atomic_json(self.path, {"before": 1})
        with patch("core.storage.os.replace", side_effect=OSError("disk error")):
            with self.assertRaises(OSError):
                atomic_json(self.path, {"after": 2})
        self.assertEqual(json.loads(self.path.read_text()), {"before": 1})
        self.assertFalse(list(self.path.parent.glob("*.tmp")))

    def test_memory_updates_do_not_lose_parallel_facts(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda i: memory.update_memory({"notes": {f"fact{i}": str(i)}}), range(25)))
        self.assertEqual(len(memory.load_memory()["notes"]), 25)


class PolicyTests(unittest.TestCase):
    def test_schema_validation_rejects_wrong_types_and_missing_fields(self):
        schema = {"type": "OBJECT", "properties": {"n": {"type": "INTEGER", "minimum": 1}}, "required": ["n"]}
        for value in ({}, {"n": "2"}, {"n": True}, {"n": 0}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                policy.validate_call(value, schema)
        policy.validate_call({"n": 3}, schema)

    def test_redaction_and_consequential_tools(self):
        data = {"api_key": "do-not-log", "nested": [{"password": "hidden"}], "text": "Bearer abcdef"}
        self.assertNotIn("do-not-log", str(policy.redact(data)))
        self.assertNotIn("hidden", str(policy.redact(data)))
        self.assertTrue(policy.approval_reason("send_message", {}))
        self.assertTrue(policy.approval_reason("code_helper", {"action": "auto"}))
        self.assertFalse(policy.approval_reason("browser_control", {"action": "fill_form"}))
        self.assertTrue(policy.approval_reason("computer_control", {"action": "hotkey"}))
        self.assertFalse(policy.approval_reason("computer_settings", {"action": "type_text"}))
        self.assertFalse(policy.approval_reason("web_search", {}))

    def test_stop_grammar_does_not_cancel_normal_requests(self):
        self.assertEqual(stop_command("Jarvis, stop!"), "cancel_current")
        self.assertEqual(stop_command("Hey Friday, stop everything safely", "Friday"), "cancel_all")
        self.assertEqual(stop_command("don't stop the music"), "")
        self.assertEqual(stop_command("research bus stop locations"), "")

    def test_generated_paths_are_contained(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self.assertEqual(contained_path(base, "src/main.py"), base / "src" / "main.py")
            for raw in ("../outside.py", "a/../../outside", "C:\\escape.py", "C:escape.py", "/etc/passwd", "file:stream", ".git/config", "../x", "x. /a", "NUL", "src/COM1.py"):
                with self.subTest(path=raw), self.assertRaises(ValueError):
                    contained_path(base, raw)


class ProcessTests(unittest.TestCase):
    def test_nonzero_exit_is_failure_even_without_error_text(self):
        result = run_process([sys.executable, "-c", "import sys; print('hello'); sys.exit(7)"], Path.cwd())
        self.assertEqual(result.returncode, 7)
        self.assertIn("hello", result.stdout)
        self.assertTrue(result.describe().startswith("status=failed"))

    def test_output_is_bounded(self):
        result = run_process([sys.executable, "-c", "print('x'*100000)"], Path.cwd())
        self.assertLess(len(result.stdout), 65_000)
        self.assertIn("truncated", result.stdout)

    def test_timeout_kills_process(self):
        started = time.monotonic()
        result = run_process([sys.executable, "-c", "import time; time.sleep(20)"], Path.cwd(), 1)
        self.assertTrue(result.timed_out)
        self.assertLess(time.monotonic() - started, 8)

    def test_cancellation_stops_running_child(self):
        event = threading.Event()
        token = cancel_event.set(event)
        timer = threading.Timer(0.3, event.set)
        timer.start()
        try:
            result = run_process([sys.executable, "-c", "import time; time.sleep(20)"], Path.cwd())
            self.assertTrue(result.cancelled)
        finally:
            cancel_event.reset(token)
            timer.join()


class TaskTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "tasks.json"
        self.managers = []

    async def asyncTearDown(self):
        for manager in self.managers:
            await manager.close()
        self.tmp.cleanup()

    def manager(self, handler, **kw):
        manager = TaskManager(self.path, handler, lambda *_: None, **kw)
        self.managers.append(manager)
        return manager

    async def until(self, condition, timeout=4):
        async with asyncio.timeout(timeout):
            while not condition():
                await asyncio.sleep(0.01)

    @staticmethod
    def step(key, tool="web_search", deps=(), **kw):
        return {"id": key, "tool": tool, "arguments": {}, "depends_on": list(deps), **kw}

    async def test_dependencies_parallelism_and_isolated_failure(self):
        count = peak = 0
        lock = threading.Lock()
        def handler(tool, args):
            nonlocal count, peak
            with lock:
                count += 1
                peak = max(peak, count)
            time.sleep(0.08)
            with lock:
                count -= 1
            return "status=failed reason=offline" if tool == "weather_report" else "status=done verified=true"
        manager = self.manager(handler, concurrency=2)
        ids = manager.submit([self.step("a"), self.step("b"), self.step("c", deps=["a", "b"]),
                              self.step("bad", "weather_report"), self.step("blocked", deps=["bad"])])
        manager.start()
        await self.until(lambda: all(j.state in {"completed", "failed", "blocked"} for j in manager.jobs.values()))
        self.assertEqual(peak, 2)
        self.assertEqual(manager.jobs[ids[-1]].state, "blocked")
        self.assertGreaterEqual(manager.jobs[ids[2]].started, manager.jobs[ids[0]].finished)

    async def test_conflicting_writes_and_foreground_reservation(self):
        running = peak = 0
        def handler(*_):
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            time.sleep(0.06)
            running -= 1
            return "status=done"
        manager = self.manager(handler)
        ids = manager.submit([self.step("a", "file_controller"), self.step("b", "code_helper")])
        async with manager.reserve("file_controller"):
            manager.start()
            await asyncio.sleep(0.08)
            self.assertTrue(all(j.state == "queued" for j in manager.jobs.values()))
        await self.until(lambda: all(j.state == "completed" for j in manager.jobs.values()))
        self.assertEqual(peak, 1)

    async def test_cancel_keeps_slot_until_legacy_tool_returns(self):
        release = threading.Event()
        manager = self.manager(lambda *_: release.wait(2) or "ok", concurrency=1)
        ids = manager.submit([self.step("a"), self.step("b")])
        manager.start()
        await self.until(lambda: manager.jobs[ids[0]].state == "running")
        manager.control("cancel", ids[0])
        await asyncio.sleep(0.06)
        self.assertEqual(manager.jobs[ids[0]].state, "cancelling")
        self.assertEqual(manager.jobs[ids[1]].state, "queued")
        release.set()
        await self.until(lambda: manager.jobs[ids[1]].state == "completed")
        self.assertEqual(manager.jobs[ids[0]].state, "cancelled")

    async def test_priority_pause_resume_and_cycle_rejection(self):
        order = []
        manager = self.manager(lambda name, args: order.append(name) or "ok", concurrency=1)
        ids = manager.submit([self.step("low", "web_search", priority=8), self.step("high", "weather_report", priority=1)])
        manager.control("pause", ids[0])
        manager.start()
        await self.until(lambda: manager.jobs[ids[1]].state == "completed")
        self.assertEqual(manager.jobs[ids[0]].state, "paused")
        manager.control("resume", ids[0])
        await self.until(lambda: manager.jobs[ids[0]].state == "completed")
        self.assertEqual(order, ["weather_report", "web_search"])
        with self.assertRaises(ValueError):
            manager.submit([self.step("a", deps=["b"]), self.step("b", deps=["a"])])

    async def test_recovery_requires_explicit_resume(self):
        manager = self.manager(lambda *_: "ok")
        ids = manager.submit([self.step("a")])
        recovered = self.manager(lambda *_: "ok")
        self.assertEqual(recovered.jobs[ids[0]].state, "interrupted")
        recovered.start()
        await asyncio.sleep(0.05)
        self.assertEqual(recovered.jobs[ids[0]].state, "interrupted")
        recovered.control("resume", ids[0])
        await self.until(lambda: recovered.jobs[ids[0]].state == "completed")

    async def test_deadline_signals_cooperative_worker(self):
        def handler(*_):
            cancel_event.get().wait(3)
            return "stopped"
        manager = self.manager(handler)
        ids = manager.submit([self.step("a", timeout=1)])
        manager.start()
        await self.until(lambda: manager.jobs[ids[0]].state == "timed_out")

    async def test_checkpoint_rejects_secrets_and_corruption(self):
        manager = self.manager(lambda *_: "ok")
        with self.assertRaises(ValueError):
            manager.submit([{**self.step("secret"), "arguments": {"api_key": "hidden"}}])
        self.path.write_text("{broken")
        with self.assertRaises(ValueError):
            TaskManager(self.path, lambda *_: "ok", lambda *_: None)

    async def test_retries_are_bounded_and_for_read_only_tools(self):
        calls = []
        manager = self.manager(lambda *_: calls.append(1) or "status=failed reason=offline")
        ids = manager.submit([self.step("search", max_retries=2)])
        manager.start()
        await self.until(lambda: manager.jobs[ids[0]].state == "failed")
        self.assertEqual(len(calls), 3)
        with self.assertRaises(ValueError):
            manager.submit([self.step("write", "file_controller", max_retries=1)])


if __name__ == "__main__":
    unittest.main()
