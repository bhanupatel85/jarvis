"""Exercise the real dispatcher, SDK schemas and Qt widgets without cloud calls."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from google.genai import types
from core import confirm, gemini
from core.tasks import TaskManager
from core.privacy import assert_local_provider, loopback_endpoint
from memory import config_manager as config, memory_manager as memory
import main


class FakeUI:
    muted = False
    current_file = None
    def __init__(self):
        self.logs = []
        self.confirmations = []
    def write_log(self, text):
        self.logs.append(text)
    def show_confirm(self, title, detail):
        self.confirmations.append((title, detail))
    def __getattr__(self, name):
        return lambda *a, **kw: None


class DispatcherTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.patches = [patch.object(config, "CONFIG_FILE", root / "api_keys.json"),
                        patch.object(config, "CONFIG_DIR", root),
                        patch.object(memory, "MEMORY_PATH", root / "memory.json")]
        for p in self.patches:
            p.start()
        self.ui = FakeUI()
        self.jarvis = main.JarvisLive(self.ui)
        self.jarvis._loop = asyncio.get_running_loop()
        self.jarvis._tasks = TaskManager(root / "tasks.json", self.jarvis._background_tool,
                                         self.jarvis._validate_background)
        confirm.resolve(False)
        confirm.bind(self.ui.show_confirm, lambda: None, self.ui.write_log)

    async def asyncTearDown(self):
        confirm.resolve(False)
        await self.jarvis._tasks.close()
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    async def test_live_sdk_accepts_task_tool_schema(self):
        cfg = self.jarvis._build_config()
        self.assertIsInstance(cfg, types.LiveConnectConfig)
        names = [t.name for tool in cfg.tools for t in tool.function_declarations]
        self.assertIn("task_manager", names)
        self.assertIn("open_app", names)
        self.assertIn("send_message", names)

    async def test_invalid_call_is_rejected_before_handler(self):
        with patch.object(self.jarvis._action_registry, "run") as handler:
            result = await self.jarvis._execute_tool(types.FunctionCall(name="web_search", args={"query": 123}))
        handler.assert_not_called()
        self.assertIn("status=failed", result.response["result"])

    async def test_approval_cannot_be_supplied_by_model(self):
        with patch.object(self.jarvis._action_registry, "run", return_value="status=done") as handler:
            result = await self.jarvis._execute_tool(types.FunctionCall(
                name="code_helper", args={"action": " RUN ", "file_path": "example.py", "confirmed": "yes"}))
            handler.assert_not_called()
            self.assertIn("CONFIRMATION_PENDING", result.response["result"])
            self.assertEqual(len(self.ui.confirmations), 1)
            confirm.resolve(True)
            async with asyncio.timeout(3):
                while not handler.called:
                    await asyncio.sleep(0.01)
                while self.jarvis._foreground_stops:
                    await asyncio.sleep(0.01)
            handler.assert_called_once()

    async def test_task_plan_routes_through_real_dispatcher(self):
        step = {"id": "research", "tool": "web_search", "arguments_json": json.dumps({"query": "test"})}
        response = await self.jarvis._execute_tool(types.FunctionCall(name="task_manager", args={"action": "submit", "steps": [step]}))
        self.assertEqual(json.loads(response.response["result"])["status"], "queued")
        self.assertEqual(len(self.jarvis._tasks.jobs), 1)
        risky = {"id": "run", "tool": "dev_agent", "arguments_json": json.dumps({"description": "hello"})}
        response = await self.jarvis._execute_tool(types.FunctionCall(name="task_manager", args={"action": "submit", "steps": [risky]}))
        self.assertIn("status=failed", response.response["result"])
        self.assertEqual(len(self.jarvis._tasks.jobs), 1)

    async def test_stop_clears_pending_approval(self):
        await self.jarvis._execute_tool(types.FunctionCall(name="code_helper", args={"action": "run"}))
        self.assertIsNotNone(confirm._pending)
        self.assertTrue(self.jarvis._handle_stop("Jarvis, stop everything"))
        self.assertIsNone(confirm._pending)

    async def test_receive_loop_hears_stop_while_a_tool_is_running(self):
        from providers.base import Msg, ToolCall, FunctionCall, ServerContent, Transcription
        from core.execution import cancel_event
        started = __import__("threading").Event()
        stopped = __import__("threading").Event()
        responses = []
        def tool(*_):
            started.set()
            event = cancel_event.get()
            if event.wait(2):
                stopped.set()
            return "status=unverified reason=cancelled"
        class Session:
            async def receive(inner):
                yield Msg(tool_call=ToolCall([FunctionCall(name="web_search", args={"query": "test"})]))
                while not started.is_set():
                    await asyncio.sleep(0.01)
                yield Msg(server_content=ServerContent(input_transcription=Transcription("Jarvis, stop")))
                await asyncio.Future()
            async def send_tool_response(inner, **kwargs):
                responses.append(kwargs)
        self.jarvis.session = Session()
        self.jarvis.audio_in_queue = asyncio.Queue()
        with patch.object(self.jarvis._action_registry, "run", side_effect=tool):
            receiver = asyncio.create_task(self.jarvis._receive_audio())
            try:
                async with asyncio.timeout(3):
                    while not stopped.is_set() or not responses:
                        await asyncio.sleep(0.01)
                self.assertIn("status=unverified", responses[0]["function_responses"][0].response["result"])
            finally:
                receiver.cancel()
                await asyncio.gather(receiver, return_exceptions=True)

    async def test_pending_approval_cannot_be_replaced_by_another_tool(self):
        confirm.request("first", "Review first", "first details", lambda: "first")
        response = confirm.request("second", "Review second", "second details", lambda: "second")
        self.assertEqual(confirm._pending.key, "first")
        self.assertIn("not queued", response)

    async def test_local_only_never_constructs_google_client_or_falls_back(self):
        config.save_providers(mode="pipeline", pipeline={"llm": "openai_compat"}, local_only=True,
                              creds={"openai_compat": {"base_url": "http://127.0.0.1:11434/v1", "model": "local"}})
        with patch.object(gemini, "client") as cloud, patch.object(gemini, "_live_call") as live, \
                patch.object(gemini, "_provider_call", side_effect=ConnectionError("local offline")):
            self.assertIsNone(gemini.call("private content"))
        cloud.assert_not_called()
        live.assert_not_called()
        config.save_providers(mode="gemini")
        with self.assertRaises(ValueError):
            self.jarvis._resolve_engine_caps()


class PrivacyTests(unittest.TestCase):
    def test_cloud_and_disguised_local_addresses_are_rejected(self):
        self.assertTrue(loopback_endpoint("http://127.0.0.1:11434/v1"))
        self.assertTrue(loopback_endpoint("http://[::1]:1234/v1"))
        for url in ("https://localhost.evil.example", "https://api.openai.com", "http://localhost@evil.example", "file:///tmp/model"):
            self.assertFalse(loopback_endpoint(url))
        with self.assertRaises(ValueError):
            assert_local_provider("elevenlabs", {})


class CodingRegressionTests(unittest.TestCase):
    def test_coding_edits_preserve_concurrent_work_and_have_backups(self):
        from actions.code_helper import _save_file
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "code.py"
            path.write_text("original")
            with self.assertRaises(RuntimeError):
                _save_file(path, "model change", expected="outdated")
            self.assertEqual(path.read_text(), "original")
            _save_file(path, "new content", expected="original")
            backups = list((path.parent / ".jarvis-backups").glob("*.bak"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(), "original")
            self.assertEqual(path.read_text(), "new content")
    def test_exit_codes_not_stderr_words_determine_command_success(self):
        from actions import code_helper, dev_agent
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root / "hello.py"
            script.write_text("import sys; print('warning', file=sys.stderr)")
            output = code_helper._run_file(script, [], 10)
            self.assertFalse(code_helper._has_error(output), output)
            script.write_text("raise SystemExit(5)")
            output = code_helper._run_file(script, [], 10)
            self.assertTrue(code_helper._has_error(output), output)
            self.assertTrue(dev_agent._has_error(output, "python hello.py"))
            self.assertTrue(dev_agent._has_error("Timed out after 30s", "python hello.py"))
            output = dev_agent._run_project("jarvis-definitely-missing-command-99881", root)
            self.assertTrue(dev_agent._has_error(output, "missing"), output)
            output = code_helper._run_file(root / "file.unknown", [], 10)
            self.assertTrue(code_helper._has_error(output), output)


class QtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_task_panel_displays_real_states_and_routes_controls(self):
        from ui import TaskPanel
        calls = []
        panel = TaskPanel(None, lambda action, key: calls.append((action, key)))
        panel.refresh([{"id": "123", "title": "Inspect project", "tool": "file_processor", "state": "running", "result": ""}])
        panel.table.selectRow(0)
        panel._selected("cancel")
        self.assertEqual(calls, [("cancel", "123")])
        self.assertEqual(panel.table.item(0, 1).text(), "running")
        panel.close()

    def test_full_window_starts_with_preserved_hud_and_task_controls(self):
        import ui
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "api_keys.json"
            config_path.write_text('{"assistant_name":"JARVIS","reduced_motion":true}')
            with patch.object(ui, "API_FILE", config_path):
                window = ui.MainWindow("face.png")
                window.show()
                self.app.processEvents()
                self.assertTrue(window.hud.reduced_motion)
                config_path.write_text(json.dumps({"providers": {"mode": "pipeline", "pipeline": {"llm": "openai_compat"}}}))
                self.assertTrue(window._check_config())
                self.assertEqual(window.hud._tmr.interval(), 100)
                window._refresh_tasks([{"id": "job", "title": "Research", "tool": "web_search", "state": "running", "result": ""}])
                self.assertIn("1 ACTIVE", window._tasks_btn.text())
                window._open_tasks()
                self.app.processEvents()
                self.assertEqual(window._task_panel.table.rowCount(), 1)
                window._task_panel.close()
                window.close()


if __name__ == "__main__":
    unittest.main()
