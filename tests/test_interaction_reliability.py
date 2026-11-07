import asyncio
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, Mock, patch
from core import accessibility, diagnostics, personal_browser
from core.uia_worker import choose, execute


def control(name='Log in', **extra):
    return dict(id='login', name=name, role='Button', visible=True, enabled=True, dialog=False, **extra)


class AccessibilitySelectionTests(unittest.TestCase):
    def test_login_alias_and_duplicate_refusal(self):
        record = control()
        self.assertEqual(choose([record], 'login')[0], record)
        self.assertEqual(choose([record, dict(record, id='other')], 'login')[1], 'ambiguous')

    def test_link_description_ignores_role_suffix(self):
        record = dict(control('Learn more'), role='Hyperlink')
        self.assertEqual(choose([record], 'the Learn more link')[0], record)

    def test_maps_labels_ignore_context_words(self):
        search = dict(control('Search Google Maps'), role='ComboBox')
        self.assertEqual(choose([search], 'the Google Maps place search input field, not the browser address bar')[0], search)
        zoom = control('Zoom in')
        self.assertEqual(choose([zoom], 'the map Zoom in button')[0], zoom)

    def test_popup_close_never_selects_browser_close(self):
        browser = dict(control('Close'), id='browser-close')
        popup = dict(browser, id='dialog-close', dialog=True)
        self.assertEqual(choose([browser, popup], 'close popup', dialog_only=True)[0]['id'], 'dialog-close')
        self.assertEqual(choose([browser], 'close popup', dialog_only=True)[1], 'not_found')

    def test_disabled_and_hidden_controls_are_not_clicked(self):
        self.assertEqual(choose([dict(control(), enabled=False)], 'login')[1], 'not_found')
        self.assertEqual(choose([dict(control(), visible=False)], 'login')[1], 'not_found')

    def test_stale_snapshot_never_sends_input(self):
        desktop = Mock()
        with patch('core.uia_worker.snapshot', return_value=([control()], {'login': Mock()})):
            result = execute({'action': 'click', 'description': 'login', 'snapshot': 'old'}, desktop, lambda: 42)
        self.assertEqual(result['status'], 'stale')
        self.assertFalse(result['attempted'])

    def test_click_without_ui_change_does_not_claim_success(self):
        target = Mock()
        desktop = Mock()
        with patch('core.uia_worker.snapshot', return_value=([control()], {'login': target})), \
             patch('core.uia_worker.time.sleep'), patch('core.uia_worker.time.monotonic', side_effect=[0, 0, 2]):
            result = execute({'action': 'click', 'description': 'login'}, desktop, lambda: 42)
        self.assertEqual(result['status'], 'unchanged')
        target.iface_invoke.Invoke.assert_called_once()
        self.assertNotIn('done', result['status'])

    def test_lost_focus_is_rejected(self):
        result = execute({'action': 'click', 'hwnd': 42}, Mock(), lambda: 99)
        self.assertEqual(result['status'], 'focus_lost')
        self.assertFalse(result['attempted'])


class PersonalReliabilityTests(unittest.TestCase):
    def test_unknown_click_outcome_never_retries_with_coordinates(self):
        from actions import computer_control as cc
        with patch.object(personal_browser, '_uia', return_value={'status': 'timeout', 'attempted': True}), \
             patch.object(cc, '_screen_find') as vision:
            with self.assertRaises(personal_browser.InteractionError):
                personal_browser.click_observed(cc, 'login')
            vision.assert_not_called()

    def test_inspect_returns_real_observed_controls(self):
        with patch.object(personal_browser, 'focus_browser', return_value=42), \
             patch.object(personal_browser, '_uia', return_value={'status': 'observed', 'controls': [control()]}):
            result = personal_browser.control({'action': 'inspect'}, 'chrome', str, Mock())
        self.assertIn('Log in', result)
        self.assertIn('UNTRUSTED', result)

    def test_popup_done_only_after_observed_dismissal(self):
        with patch.object(personal_browser, 'focus_browser', return_value=42), \
             patch.object(personal_browser, 'click_observed', return_value={'status': 'dialog_dismissed'}):
            result = personal_browser.control({'action': 'dismiss_popup'}, 'chrome', str, Mock())
        self.assertIn('popup_dismissed=true', result)
        self.assertIn('status=done', result)

    def test_log_contains_no_typed_content(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(diagnostics, 'LOG_PATH', Path(directory)/'events.jsonl'):
            diagnostics.record('click', 'unchanged', backend='uia', attempted=True)
            entry = json.loads(diagnostics.LOG_PATH.read_text())
        self.assertEqual(set(entry), {'at', 'action', 'status', 'backend', 'error_type', 'attempted'})

    def test_accessibility_timeout_is_explicit(self):
        import subprocess
        with patch('core.accessibility.subprocess.run', side_effect=subprocess.TimeoutExpired('worker', 10)):
            result = accessibility.request('click', description='login')
        self.assertEqual(result['status'], 'timeout')
        self.assertTrue(result['attempted'])
