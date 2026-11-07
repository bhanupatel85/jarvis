import unittest
from unittest.mock import patch
from core import public_data as data
from actions.currency_convert import currency_action
from actions.weather_report import weather_action

class PublicDataTests(unittest.TestCase):
    def setUp(self):
        data._cache.clear()

    def test_conversion_preserves_rate_date(self):
        with patch.object(data, 'fetch', return_value=({'rate': 84, 'date': '2026-10-29'}, 'stamp', True)):
            result = data.currency(10, 'usd', 'inr')
        self.assertIn('840.00 INR', result)
        self.assertIn('2026-10-29', result)
        self.assertIn('cached', result)

    def test_invalid_amount_never_calls_provider(self):
        with patch.object(data, 'fetch') as fetch:
            for amount in [-1, float('nan'), float('inf')]:
                with self.assertRaises(ValueError):
                    data.currency(amount, 'USD', 'INR')
            fetch.assert_not_called()

    def test_cache_expiry(self):
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"ok":true}'
        with patch.object(data, 'urlopen', return_value=response) as request, patch.object(data.time, 'monotonic', return_value=0):
            self.assertFalse(data.fetch('https://example.com', ttl=10)[2])
            self.assertTrue(data.fetch('https://example.com', ttl=10)[2])
            self.assertEqual(request.call_count, 1)
        with patch.object(data, 'urlopen', return_value=response) as request, patch.object(data.time, 'monotonic', return_value=11):
            self.assertFalse(data.fetch('https://example.com', ttl=10)[2])
            request.assert_called_once()

    def test_specific_news_retains_search(self):
        with patch.object(data, 'fetch') as fetch:
            self.assertIsNone(data.headlines('space exploration in India'))
            fetch.assert_not_called()

    def test_weather_tomorrow(self):
        geo = {'results': [{'name': 'Delhi', 'latitude': 28, 'longitude': 77}]}
        forecast = {'daily': {'time': ['today', 'tomorrow'], 'temperature_2m_min': [20, 21], 'temperature_2m_max': [30, 31], 'precipitation_probability_max': [0, 10]}}
        with patch.object(data, 'fetch', side_effect=[(geo, '', False), (forecast, 'stamp', False)]):
            self.assertIn('low 21 C', data.weather('Delhi', 'tomorrow'))

    def test_actions_report_outage_without_inventing_data(self):
        with patch('actions.weather_report.weather', side_effect=OSError):
            self.assertIn('no current weather was verified', weather_action({'city': 'Delhi'}))
        with patch('actions.currency_convert.currency', side_effect=OSError):
            self.assertIn('no current rate was verified', currency_action({'amount': 1, 'base': 'USD', 'quote': 'INR'}))

    def test_news_outage_uses_existing_fallback(self):
        from actions import web_search
        with patch.object(data, 'headlines', side_effect=OSError), patch.object(web_search, '_ddg_news', return_value=[{'title': 'A meaningful headline about technology today', 'url': 'https://example.com', 'source': 'Example'}]):
            self.assertIn('meaningful headline', web_search._news('technology'))

if __name__ == '__main__':
    unittest.main()
