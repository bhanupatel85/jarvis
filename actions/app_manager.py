"""Find and install Windows packages without shell interpolation."""
import platform
import re
import shutil
from pathlib import Path
from core import outcome
from core.execution import run_process


def app_manager(params, **kwargs):
    if platform.system() != "Windows" or not shutil.which("winget"):
        return outcome.failed("app_manager", "Windows Package Manager (winget) is unavailable")
    action = params.get("action", "search")
    if action == "search":
        query = str(params.get("query", "")).strip()
        if not query or query.startswith("-"):
            return outcome.failed("app_manager", "Provide an application name")
        args = ["winget", "search", "--query", query, "--source", "winget", "--disable-interactivity"]
    elif action == "install":
        package = str(params.get("package_id", ""))
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{1,180}", package):
            return outcome.failed("app_manager", "Choose an exact package ID from search first")
        args = ["winget", "install", "--id", package, "--exact", "--source", "winget",
                "--silent", "--disable-interactivity", "--accept-package-agreements"]
    else:
        return outcome.failed("app_manager", "Unknown action")
    result = run_process(args, Path.cwd(), timeout=300 if action == "install" else 30)
    if result.returncode != 0:
        return outcome.failed("app_manager", (result.stderr or result.stdout or "Package operation failed")[-3000:])
    if action == "search":
        return result.stdout[-6000:]
    check = run_process(["winget", "list", "--id", package, "--exact", "--disable-interactivity"], Path.cwd(), timeout=30)
    if check.returncode == 0 and package.casefold() in check.stdout.casefold():
        return outcome.done("app_manager", package=package, verified=True)
    return outcome.unverified("app_manager", "Installer returned successfully but installation could not be verified")


TOOL = {
    "name": "app_manager",
    "description": "Search for Windows applications and install the exact package requested by the user. Search first to identify the package ID; installation requires spoken human confirmation. Never select an ambiguous match without asking.",
    "parameters": {"type": "OBJECT", "properties": {
        "action": {"type": "STRING", "enum": ["search", "install"]},
        "query": {"type": "STRING"},
        "package_id": {"type": "STRING"}}, "required": ["action"]},
    "handler": app_manager,
}
