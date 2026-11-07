import threading
import unittest
from concurrent.futures import Future, ThreadPoolExecutor
from unittest.mock import MagicMock, patch

from core import public_data as data
from core.policy import resources_for
from actions.air_quality_report import air_quality_action


class PublicDataUpgradeTests(unittest.TestCase):
    def setUp(self):
        data._cache.clear()
        data._inflight.clear()

    def test_refresh_bypasses_fresh_cache(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"ok":true}'
        with patch.object(data, 'urlopen', return_value=response) as request:
            data.fetch('https://example.com')
            self.assertTrue(data.fetch('https://example.com')[2])
            self.assertFalse(data.fetch('https://example.com', refresh=True)[2])
            self.assertEqual(request.call_count, 2)

    def test_simultaneous_requests_share_one_network_call(self):
        started, follower_waiting, release = (threading.Event() for _ in range(3))
        class ObservedFuture(Future):
            def result(self, timeout=None):
                follower_waiting.set()
                return super().result(timeout)
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"ok":true}'
        def network(*args, **kwargs):
            started.set()
            if not release.wait(3):
                raise TimeoutError('Test did not release request')
            return response
        with patch.object(data, 'Future', ObservedFuture), patch.object(data, 'urlopen', side_effect=network) as request, ThreadPoolExecutor(2) as pool:
            first = pool.submit(data.fetch, 'https://example.com')
            self.assertTrue(started.wait(2))
            second = pool.submit(data.fetch, 'https://example.com')
            try:
                self.assertTrue(follower_waiting.wait(2))
            finally:
                release.set()
            a, b = first.result(3), second.result(3)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(a[:2], b[:2])
        self.assertFalse(a[2])
        self.assertTrue(b[2])
        self.assertFalse(data._inflight)

    def test_errors_and_oversized_responses_are_not_cached(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'x' * 2_000_001
        with patch.object(data, 'urlopen', side_effect=[OSError('offline'), response]):
            with self.assertRaises(OSError):
                data.fetch('https://example.com')
            with self.assertRaises(ValueError):
                data.fetch('https://example.com')
        self.assertFalse(data._cache)
        self.assertFalse(data._inflight)

    def test_failed_refresh_does_not_serve_old_data(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"ok":true}'
        with patch.object(data, 'urlopen', return_value=response):
            data.fetch('https://example.com')
        with patch.object(data, 'urlopen', side_effect=OSError('offline')):
            with self.assertRaises(OSError):
                data.fetch('https://example.com', refresh=True)

    def test_country_filter_and_coordinate_validation(self):
        geo = {'results': [{'name': 'Hyderabad', 'latitude': 17, 'longitude': 78}]}
        with patch.object(data, 'fetch', return_value=(geo, '', False)) as fetch:
            data.resolve_location('Hyderabad, Telangana', 'in')
            self.assertIn('countryCode=IN', fetch.call_args.args[0])
            self.assertIn('Hyderabad%2C+Telangana', fetch.call_args.args[0])
        with patch.object(data, 'fetch') as fetch:
            with self.assertRaises(ValueError):
                data.resolve_location('Hyderabad', 'India')
            fetch.assert_not_called()
        geo['results'][0]['latitude'] = float('nan')
        with patch.object(data, 'fetch', return_value=(geo, '', False)):
            with self.assertRaises(ValueError):
                data.resolve_location('Hyderabad')

    def test_air_quality_labels_us_scale_source_and_model_time(self):
        place = {'name': 'Hyderabad', 'latitude': 17, 'longitude': 78, 'country': 'India'}
        reading = {'current': {'time': '2026-11-02T12:00', 'us_aqi': 101, 'pm2_5': 37.2, 'pm10': None}, 'timezone': 'Asia/Kolkata'}
        with patch.object(data, 'resolve_location', return_value=place), patch.object(data, 'fetch', return_value=(reading, 'original retrieval', True)):
            result = data.air_quality('Hyderabad', 'IN')
        for text in ('US AQI 101', 'unhealthy for sensitive groups', '37.2', '2026-11-02T12:00', 'CAMS', 'not an Indian CPCB', 'original retrieval', 'cached'):
            self.assertIn(text, result)
        self.assertNotIn('PM10 None', result)

    def test_missing_air_quality_returns_failed_outcome(self):
        with patch('actions.air_quality_report.air_quality', side_effect=ValueError('No valid readings')):
            self.assertIn('status=failed', air_quality_action({'city': 'Hyderabad'}))
        with patch('actions.air_quality_report.air_quality', side_effect=OSError):
            self.assertIn('no current reading was verified', air_quality_action({'city': 'Hyderabad'}))

    def test_invalid_air_quality_readings_are_not_reported(self):
        with patch.object(data, 'resolve_location', return_value={'latitude': 17, 'longitude': 78}), patch.object(data, 'fetch', return_value=({'current': {'us_aqi': None, 'pm2_5': float('nan'), 'pm10': -1}}, 'stamp', False)):
            with self.assertRaises(ValueError):
                data.air_quality('Hyderabad')

    def test_read_only_tools_do_not_lock_desktop(self):
        for name in ('weather_report', 'currency_convert', 'air_quality_report', 'api_directory'):
            self.assertEqual(resources_for(name), ())

    def test_broad_news_uses_rss_specific_news_retains_search(self):
        from xml.etree.ElementTree import fromstring
        root = fromstring('<rss><channel><item><title>Technology story</title><link>https://example.com/news</link><pubDate>date</pubDate></item></channel></rss>')
        with patch.object(data, 'fetch', return_value=(root, 'stamp', False)) as fetch:
            self.assertIn('Technology story', data.headlines('latest technology news'))
            self.assertIn('/technology/rss.xml', fetch.call_args.args[0])
        with patch.object(data, 'fetch') as fetch:
            self.assertIsNone(data.headlines('Medchal road repair news'))
            fetch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
