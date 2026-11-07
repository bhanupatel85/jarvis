import tempfile
import unittest
from pathlib import Path
from core.project_knowledge import search
from core.development_workspace import prepare, review

class DevelopmentTests(unittest.TestCase):
    def test_search_excludes_private_config_and_returns_lines(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'core').mkdir(); (root/'config').mkdir()
            (root/'core'/'sample.py').write_text('weather retrieval example\n')
            (root/'config'/'api_keys.json').write_text('{"password":"weather"}')
            results=search('weather', root)
            self.assertEqual(len(results),1)
            self.assertEqual(results[0]['line'],1)
            self.assertIn('sample.py',results[0]['path'])

    def test_source_search_redacts_recognizable_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); (root/'core').mkdir()
            (root/'core'/'sample.py').write_text('example api_key=supersecretvalue')
            self.assertNotIn('supersecretvalue',search('example',root)[0]['text'])

    def test_workspace_review_does_not_change_original(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'source'; root.mkdir()
            (root/'main.py').write_text('answer = 1\n')
            (root/'memory').mkdir(); (root/'memory'/'personal.json').write_text('private')
            workspaces=Path(folder)/'workspaces'
            item=prepare(root,workspaces)
            working=Path(item['working'])
            self.assertFalse((working/'memory'/'personal.json').exists())
            (working/'main.py').write_text('answer = (\n')
            report=review(item['id'],workspaces)
            self.assertEqual(report['changed_files'],['main.py'])
            self.assertTrue(report['syntax_errors'])
            self.assertFalse(report['applied'])
            self.assertEqual((root/'main.py').read_text(),'answer = 1\n')
            self.assertIn('answer =',Path(report['diff']).read_text())

    def test_invalid_workspace_id(self):
        with self.assertRaises(ValueError):review('../escape')

    def test_reference_catalog_searchable(self):
        self.assertTrue(any('development-references' in h['path'] for h in search('retrieval document knowledge')))

if __name__=='__main__':unittest.main()
