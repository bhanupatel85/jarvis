import tempfile
import unittest
from pathlib import Path
from core import self_development as dev
from core.policy import approval_reason

class SelfDevelopmentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'app';self.root.mkdir()
        self.workspaces=Path(self.temp.name)/'workspaces'
        (self.root/'feature.py').write_text('value = 1\n')
        (self.root/'tests').mkdir()
        (self.root/'tests'/'__init__.py').write_text('')
        (self.root/'tests'/'test_feature.py').write_text('import unittest\nimport feature\nclass T(unittest.TestCase):\n def test_value(self): self.assertEqual(feature.value, 2)\n')
        self.item=dev.start(self.root,self.workspaces)
        self.working=Path(self.item['working'])
        (self.working/'feature.py').write_text('value = 2\n')

    def check(self):
        return dev.check(self.item['id'],['tests.test_feature'],self.root,self.workspaces)

    def apply(self, report):
        return dev.apply(self.item['id'],report['review_token'],self.root,self.workspaces)

    def test_end_to_end_tests_apply_and_rollback(self):
        report=self.check();self.assertTrue(report['passed'],report['result'])
        self.assertEqual(report['test_count'],1)
        self.apply(report)
        self.assertIn('2',(self.root/'feature.py').read_text())
        dev.rollback(self.item['id'],self.root,self.workspaces)
        self.assertIn('1',(self.root/'feature.py').read_text())

    def test_later_working_edits_block_apply(self):
        report=self.check();(self.working/'feature.py').write_text('value = 3\n')
        with self.assertRaises(ValueError):self.apply(report)

    def test_later_source_edits_block_apply(self):
        report=self.check();(self.root/'feature.py').write_text('value = 9\n')
        with self.assertRaises(ValueError):self.apply(report)

    def test_failing_tests_block_apply(self):
        (self.working/'feature.py').write_text('value = 7\n')
        report=self.check();self.assertFalse(report['passed'])
        with self.assertRaises(ValueError):self.apply(report)

    def test_later_edits_block_rollback(self):
        self.apply(self.check());(self.root/'feature.py').write_text('value = 9\n')
        with self.assertRaises(ValueError):dev.rollback(self.item['id'],self.root,self.workspaces)

    def test_zero_tests_not_passing(self):
        (self.working/'tests'/'test_feature.py').write_text('')
        self.assertFalse(self.check()['passed'])

    def test_on_screen_approval_required(self):
        for action in ('check','apply','rollback'):
            self.assertTrue(approval_reason('self_development',{'action':action}))

if __name__=='__main__':unittest.main()
