import unittest
from unittest.mock import patch, Mock
from core import personal_browser


class RenderingWaitTests(unittest.TestCase):
    def test_wait_is_bounded_and_does_not_send_input(self):
        with patch.object(personal_browser, 'focus_browser', return_value=42), patch.object(personal_browser.time, 'sleep') as sleep:
            result = personal_browser.control({'action': 'wait', 'seconds': 2}, 'chrome', str, Mock())
        sleep.assert_called_once_with(2)
        self.assertIn('status=unverified', result)

    def test_invalid_wait_does_not_sleep(self):
        with patch.object(personal_browser, 'focus_browser', return_value=42), patch.object(personal_browser.time, 'sleep') as sleep, patch('core.diagnostics.record'):
            result = personal_browser.control({'action': 'wait', 'seconds': 90}, 'chrome', str, Mock())
        sleep.assert_not_called()
        self.assertIn('status=failed', result)
