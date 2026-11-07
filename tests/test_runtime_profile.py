import unittest
from unittest.mock import patch
from core.runtime_profile import profile_for_ram
from core import personal_browser


class HardwareAndInputTests(unittest.TestCase):
    def test_current_pc_can_overlap_two_lightweight_jobs(self):
        profile = profile_for_ram(11.9)
        self.assertEqual(profile.task_concurrency, 2)
        self.assertEqual(profile_for_ram(4).task_concurrency, 1)
        self.assertTrue(profile.reduced_motion)
        self.assertEqual(profile_for_ram(32).task_concurrency, 3)

    def test_unverified_field_focus_never_allows_typing(self):
        with patch.object(personal_browser, '_uia', return_value={
                'status': 'unverified', 'attempted': True}):
            with self.assertRaises(personal_browser.InteractionError):
                personal_browser.click_observed(None, 'Password', editing=True)
