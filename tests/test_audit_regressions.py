import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from core.development_workspace import prepare
from core import public_data
from core import self_development as dev

class AuditRegressions(unittest.TestCase):
    def test_snapshot_includes_prompt_plugins_and_config_code_not_secrets(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'app';root.mkdir()
            for name in ('core','plugins','config'):(root/name).mkdir()
            for name in ('core/prompt.txt','plugins/example.py','config/__init__.py','requirements.txt'):
                (root/name).write_text('example\n')
            (root/'config/api_keys.json').write_text('private')
            item=prepare(root,Path(folder)/'workspaces')
            working=Path(item['working'])
            self.assertTrue((working/'core/prompt.txt').exists())
            self.assertTrue((working/'plugins/example.py').exists())
            self.assertTrue((working/'config/__init__.py').exists())
            self.assertTrue((working/'requirements.txt').exists())
            self.assertFalse((working/'config/api_keys.json').exists())

    def test_currency_rejects_boolean_and_overflow(self):
        with self.assertRaises(ValueError):public_data.currency(True,'USD','INR')
        with patch.object(public_data,'fetch',return_value=({'rate':100,'date':'2026-10-30'},'now',False)):
            with self.assertRaises(ValueError):public_data.currency(1e308,'USD','INR')

    def test_missing_city_does_not_call_provider(self):
        with patch.object(public_data,'fetch') as fetch:
            with self.assertRaises(ValueError):public_data.weather(None)
            fetch.assert_not_called()

    def test_stale_bytecode_cannot_make_broken_code_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'app';root.mkdir();(root/'tests').mkdir()
            (root/'tests/__init__.py').write_text('')
            (root/'feature.py').write_text('value = 1\n')
            (root/'tests/test_feature.py').write_text('import unittest, feature\nclass T(unittest.TestCase):\n def test_value(self): self.assertEqual(feature.value, 1)\n')
            workspaces=Path(folder)/'workspaces';item=dev.start(root,workspaces)
            first=dev.check(item['id'],['tests.test_feature'],root,workspaces)
            self.assertTrue(first['passed'],first['result'])
            path=Path(item['working'])/'feature.py';stamp=path.stat().st_mtime
            path.write_text('value = 2\n');os.utime(path,(stamp,stamp))
            second=dev.check(item['id'],['tests.test_feature'],root,workspaces)
            self.assertFalse(second['passed'])

if __name__=='__main__':unittest.main()
