"""Shared validation, redaction and human approval rules for tool dispatch."""
from __future__ import annotations

import json
import math
import re

_SECRET = re.compile(r"(?:api[_ -]?key|password|passwd|secret|authorization|access[_ -]?token|private[_ -]?key)", re.I)
_VALUES = re.compile(r"(?i)(bearer\s+\S+|sk-[A-Za-z0-9_-]{12,}|AIza[A-Za-z0-9_-]{20,}|-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?-----END [^-]*PRIVATE KEY-----)")
_CREDENTIAL_TEXT = re.compile(r"(?i)\b(api[_ -]?key|password|passwd|access[_ -]?token|secret)\s*(?:is\s+|[:=]\s*)\S+")


def redact(value):
    if isinstance(value, dict):
        if any(str(value.get(key, '')).strip().lower() in {'password', 'your password', 'enter your password'}
               or _SECRET.search(str(value.get(key, ''))) for key in ('label', 'description', 'selector')):
            value = {k: ('[REDACTED]' if k in {'value', 'text'} else v) for k, v in value.items()}
        return {k: "[REDACTED]" if _SECRET.search(str(k)) else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return _CREDENTIAL_TEXT.sub("[REDACTED]", _VALUES.sub("[REDACTED]", value))
    return value


def validate(value, schema: dict, path="arguments", depth=0):
    """Validate the JSON-schema subset declared by this project's tools."""
    if depth > 16:
        raise ValueError("Arguments are nested too deeply.")
    kind = str(schema.get("type", "")).lower()
    checks = {"object": lambda x: isinstance(x, dict), "array": lambda x: isinstance(x, list),
              "string": lambda x: isinstance(x, str), "boolean": lambda x: isinstance(x, bool),
              "integer": lambda x: isinstance(x, int) and not isinstance(x, bool),
              "number": lambda x: isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)}
    if kind in checks and not checks[kind](value):
        raise ValueError(f"{path} must be {kind}.")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path} is not an allowed value.")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                raise ValueError(f"{path}.{key} is required.")
        if schema.get("additionalProperties") is False and set(value) - set(props):
            raise ValueError(f"{path} contains unknown fields.")
        for key, item in value.items():
            if key in props:
                validate(item, props[key], f"{path}.{key}", depth + 1)
    if isinstance(value, list):
        if len(value) > schema.get("maxItems", 100):
            raise ValueError(f"{path} has too many entries.")
        for i, item in enumerate(value):
            validate(item, schema.get("items", {}), f"{path}[{i}]", depth + 1)
    if isinstance(value, str) and len(value) > schema.get("maxLength", 100_000):
        raise ValueError(f"{path} is too long.")
    if kind in ("number", "integer"):
        if value < schema.get("minimum", -math.inf) or value > schema.get("maximum", math.inf):
            raise ValueError(f"{path} is outside the permitted range.")


def validate_call(args, schema):
    if len(json.dumps(args, allow_nan=False)) > 150_000:
        raise ValueError("Tool arguments are too large.")
    validate(args, schema)


def approval_reason(name: str, args: dict, *, plugin=False) -> str:
    action = str(args.get("action", "auto" if name == "code_helper" else "")).lower().strip()
    if name == "self_development" and action in {"check", "apply", "rollback"}:
        return "Run development tests with your account permissions" if action == "check" else "Apply reviewed Jarvis source changes or restore a development backup"
    if plugin:
        return "Run a third-party plugin with access to your computer"
    if name == "app_manager" and action == "install":
        return "Install the requested application using its exact package ID"
    if name == "dev_agent":
        return "Generate and execute a project, including dependency installation"
    if name == "code_helper" and action in ("run", "build", "auto", "screen_debug"):
        return "Run or repair code with your account's permissions"
    if name == "send_message":
        return "Send an external message"
    if name == "computer_control" and action not in {
            "click", "double_click", "right_click", "type", "type_text", "press", "press_key", "close_app",
            "screenshot", "screen_find", "focus_window", "list_windows", "get_mouse_position", "move", "scroll"}:
        return "Control mouse or keyboard input, which may submit data or run commands"
    if name == "computer_settings" and not action:
        return "Send keyboard input or resolve an unspecified system operation"
    if name == "desktop_control" and action == "clean":
        return "Clean files from the desktop"
    if name == "browser_control" and action in ("submit", "execute_js", "evaluate"):
        return "Interact with a website; this may submit data or change an account"
    if name in {"browser_control", "windows_control"} and action in ("click", "smart_click", "press", "set_checked"):
        target = " ".join(str(args.get(k, "")) for k in ("text", "description", "selector", "key"))
        if re.search(r"buy|purchase|pay\b|transfer|delete|remove.account|send\b|publish|subscribe|place.order", target, re.I):
            return "Confirm a consequential website operation"
    if name == "file_controller" and action in ("delete", "remove", "delete_file", "delete_folder"):
        return "Delete a file or folder"
    return ""


def resources_for(name: str) -> tuple[str, ...]:
    if name in {"web_search", "weather_report", "currency_convert", "air_quality_report", "api_directory", "flight_finder", "youtube_video", "system_status"}:
        return ()
    if name in {"file_processor", "file_controller", "code_helper", "dev_agent"}:
        return ("filesystem",)
    # GUI input is a shared resource, including unknown plugins.
    return ("desktop", "filesystem")

