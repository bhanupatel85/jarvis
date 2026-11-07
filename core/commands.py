"""Small exact control grammar; ordinary requests still go to the model."""
import re


def stop_command(text: str, assistant_name="Jarvis") -> str:
    text = re.sub(r"[^\w\s]", " ", text.casefold()).strip()
    name = re.escape(assistant_name.casefold())
    text = re.sub(rf"^(?:hey\s+)?(?:{name}|jarvis)\s+", "", text)
    text = " ".join(text.split())
    if text in {"stop everything", "stop everything safely", "cancel all tasks", "stop all tasks"}:
        return "cancel_all"
    if text in {"stop", "stop speaking", "be quiet", "cancel current task", "cancel the current task"}:
        return "cancel_current"
    return ""
