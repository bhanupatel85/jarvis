import unittest
from unittest.mock import patch
from core import confirm, policy


class VoiceConfirmationTests(unittest.TestCase):
    def test_only_exact_user_reply_resolves(self):
        with patch.object(confirm, 'pending_title', return_value='Install app'), patch.object(confirm, 'resolve') as resolve:
            self.assertFalse(confirm.resolve_text('yes confirm but do not install yet'))
            resolve.assert_not_called()
            self.assertTrue(confirm.resolve_text('Yes, confirm.'))
            resolve.assert_called_once_with(True)

    def test_cancel_and_no_pending(self):
        with patch.object(confirm, 'pending_title', return_value='Delete'), patch.object(confirm, 'resolve') as resolve:
            self.assertTrue(confirm.resolve_text("don't confirm"))
            resolve.assert_called_once_with(False)
        with patch.object(confirm, 'pending_title', return_value=''):
            self.assertFalse(confirm.resolve_text('confirm'))

    def test_routine_and_sensitive_operations(self):
        for action in ('type', 'fill_form', 'open_result', 'smart_type'):
            self.assertFalse(policy.approval_reason('browser_control', {'action': action}))
        self.assertTrue(policy.approval_reason('browser_control', {'action': 'smart_click', 'description': 'Pay now'}))
        self.assertTrue(policy.approval_reason('app_manager', {'action': 'install'}))
        self.assertFalse(policy.approval_reason('app_manager', {'action': 'search'}))
