import base64
import unittest
from pathlib import Path
from unittest.mock import patch

from core import api_catalog as catalog
from core.action_loader import discover_actions, strip_meta
from actions.api_directory import directory_action

SAMPLE = '''### Transport
| API | Description | Auth | HTTPS | CORS |
|:---|:---|:---|:---|:---|
| [Metro](https://example.com/metro) | Bus \\| rail data | No | Yes | Unknown |
| [Metro](https://example.com/metro) | Duplicate | No | Yes | Unknown |
| [Taxi](https://example.com/taxi) | Taxi data | `apiKey` | Yes | No |
| [Bad](javascript:alert) | No execution | No | Yes | No |
'''


class ApiCatalogTests(unittest.TestCase):
    def setUp(self):
        self.previous = catalog._updated_catalog
        catalog._updated_catalog = None

    def tearDown(self):
        catalog._updated_catalog = self.previous

    def test_parser_keeps_auth_category_escaped_pipes_and_deduplicates(self):
        entries = catalog.parse_readme(SAMPLE)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]['description'], 'Bus | rail data')
        self.assertEqual(entries[1]['auth'], 'apiKey')
        self.assertEqual(entries[0]['category'], 'Transport')

    def test_snapshot_has_full_directory_and_no_network_on_search(self):
        data = catalog.bundled_catalog()
        self.assertGreater(len(data['entries']), 2000)
        self.assertGreaterEqual(len({e['category'] for e in data['entries']}), 50)
        with patch.object(catalog, 'fetch') as fetch:
            result = catalog.search('Frankfurter', auth='no_key')
            self.assertIn('Frankfurter', result)
            self.assertIn('not supplied keys', result)
            fetch.assert_not_called()

    def test_filters_and_limit(self):
        snapshot = {'entries': catalog.parse_readme(SAMPLE), 'retrieved_at': 'date'}
        with patch.object(catalog, 'bundled_catalog', return_value=snapshot):
            no_key = catalog.search(category='transport', auth='no_key', limit=1)
            keyed = catalog.search(auth='key_required')
            categories = catalog.search(action='categories')
            self.assertIn('https://example.com/metro', no_key)
            self.assertNotIn('https://example.com/taxi', no_key)
            self.assertIn('https://example.com/taxi', keyed)
            self.assertNotIn('https://example.com/metro', keyed)
            self.assertIn('Transport: 2', categories)

    def test_invalid_arguments_never_refresh(self):
        with patch.object(catalog, 'fetch') as fetch:
            for args in ({'limit': 26}, {'limit': True}, {'query': 'x' * 201}, {'auth': 'password'}, {'action': 'execute'}):
                with self.assertRaises(ValueError):
                    catalog.search(refresh=True, **args)
            fetch.assert_not_called()

    def test_refresh_uses_only_fixed_github_endpoint_and_keeps_new_catalog(self):
        payload = {'content': base64.b64encode(SAMPLE.encode()).decode()}
        with patch.object(catalog, 'fetch', return_value=(payload, 'new time', False)) as fetch:
            result = catalog.search('Metro', refresh=True)
            self.assertIn('new time', result)
            self.assertEqual(fetch.call_args.args[0], catalog.README_API)
            self.assertTrue(fetch.call_args.kwargs['refresh'])
        with patch.object(catalog, 'fetch') as fetch:
            self.assertIn('new time', catalog.search('Metro'))
            fetch.assert_not_called()

    def test_refresh_failure_uses_dated_snapshot(self):
        with patch.object(catalog, 'fetch', side_effect=OSError('offline')):
            result = catalog.search('weather', refresh=True)
        self.assertIn('Refresh unavailable', result)
        self.assertIn('2026-11-02', result)

    def test_directory_result_is_untrusted_and_failure_is_structured(self):
        result = directory_action({'query': 'Frankfurter'})
        self.assertTrue(result.startswith('<<<UNTRUSTED source=api_directory>>>'))
        self.assertIn('status=failed', directory_action({'limit': -1}))

    def test_discovery_and_google_sdk_accept_new_tools(self):
        from google.genai import types
        root = Path(__file__).resolve().parents[1]
        registry = discover_actions(root / 'actions', logger=lambda _: None)
        declarations = strip_meta(registry.get_tool_declarations())
        names = {d['name'] for d in declarations}
        self.assertTrue({'api_directory', 'air_quality_report', 'weather_report', 'currency_convert'} <= names)
        for declaration in declarations:
            types.FunctionDeclaration(**declaration)


if __name__ == '__main__':
    unittest.main()
