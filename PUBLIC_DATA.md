# Jarvis public data and API directory

The main app (`main.py`) discovers `weather_report`, `currency_convert`, `air_quality_report` and `api_directory` at startup. Restart Jarvis manually after installing this change. Existing news calls, including the startup briefing, use RSS for supported general topics and retain search fallbacks for specific queries or RSS outages. Automatic clap/voice launch settings are unaffected.

Try:
- What is the weather in Hyderabad tomorrow?
- Convert 100 USD to INR.
- Give me technology news.
- What is the air quality in Hyderabad, India?
- Find no-key transport APIs in the API directory.
- List the API directory categories.
- Refresh the API directory and find weather APIs.

Providers:
- Open-Meteo forecast and geocoding: https://open-meteo.com/en/docs — current model estimates and today/tomorrow daily forecasts. Location is resolved to the provider's first match and echoed in the response; specify a more precise city if needed. Free endpoint usage is subject to provider terms, including noncommercial restrictions.
- Frankfurter: https://frankfurter.dev/ — daily reference rates, not trading ticks. Amounts are converted locally. Responses include the provider's rate date.
- Open-Meteo / CAMS: https://open-meteo.com/en/docs/air-quality-api — US AQI, PM2.5 and PM10 model estimates with model time. Not Indian CPCB station AQI or street-level sensor measurements. Missing readings are not invented.
- BBC RSS: https://feeds.bbci.co.uk/news/world/rss.xml — world, technology, business and science feed topics. Publication dates and article links accompany headlines. Feed content remains subject to BBC terms.

No API keys or new packages are required for the integrated providers. Calls use five-second socket timeouts, a 2 MB response limit, and a 128-entry in-memory cache: weather 5 minutes, air quality 10 minutes, city lookup 24 hours, rates 1 hour, headlines 3 minutes. Cache hits show the original retrieval time. Concurrent misses for one resource share one request. At most 32 resources can be in flight through this helper; followers have a six-second deadline. Socket timeouts do not guarantee an overall wall-clock deadline. Explicit refresh bypasses recent provider data, reuses location lookup and shares simultaneous requests. Errors are not cached; expired results are never served as current data. Independent data tools do not take screen/filesystem locks. RSS outages retain the existing bounded DDG/Gemini path.

The bundled [public-apis directory](https://github.com/public-apis/public-apis) contains 2,136 API listings across 51 categories in the fetched API tables. Search by topic, category and authentication requirement to get documentation links and HTTPS/CORS metadata. Listings can become outdated: check pricing, availability and terms with each provider. The directory's MIT license is included in `core/data/PUBLIC_APIS_LICENSE.txt`.

`apiKey`, `OAuth` and `X-Mashape-Key` describe credentials a provider requires. They are not actual keys. Jarvis does not collect shared credentials, create accounts or automatically execute directory URLs. Catalog search does not activate every API. `no_key` includes listings marked No or User-Agent; neither label guarantees unrestricted or free usage.

Ordinary directory queries read the bundled snapshot without network access. An explicit refresh fetches only GitHub's fixed README endpoint, retains the new catalog in memory, and falls back to the dated bundled snapshot on failure. Provider descriptions are wrapped as untrusted reference data. City/region names and country filters help disambiguate weather/AQI locations; the resolved location is shown.

Run tests: `.venv\Scripts\python.exe -m unittest discover -s tests -p test_public_data*.py -v`, plus `test_api_catalog.py` and `test_integration.py`. These cover providers, cache expiry/refresh/concurrency, catalog parsing/filtering, failures and tool discovery/SDK schemas. Voice recognition still requires a separate live test.
