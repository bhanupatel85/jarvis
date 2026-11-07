"""Explicit AI-provider privacy boundary; does not block ordinary web browsing."""
from urllib.parse import urlsplit
import ipaddress


def loopback_endpoint(url):
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        local = host.casefold() == "localhost"
        if not local:
            local = ipaddress.ip_address(host).is_loopback
        return bool(local and parsed.scheme in {"http", "https"} and not parsed.username and not parsed.password)
    except ValueError:
        return False


def assert_local_provider(provider_id, cfg):
    if provider_id in {"system_tts", "piper"}:
        return
    if provider_id == "whisper" and cfg.get("backend", "local") == "local":
        return
    if provider_id in {"openai_compat", "whisper"} and loopback_endpoint(cfg.get("base_url", "")):
        return
    raise ValueError(f"Local AI only: {provider_id or 'no provider'} is not a configured local provider. Cloud fallback is disabled.")


def assert_local_pipeline():
    from memory.config_manager import get_pipeline, get_provider_config, get_provider_mode
    if get_provider_mode() != "pipeline":
        raise ValueError("Local AI only requires MY OWN SETUP; Gemini Live is disabled.")
    for slot, pid in get_pipeline().items():
        if pid:
            assert_local_provider(pid, get_provider_config(pid))
