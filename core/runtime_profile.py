"""Small, offline hardware profile. Never probes accounts or installs models."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class RuntimeProfile:
    name: str
    ram_gb: float
    task_concurrency: int
    task_capacity: int
    reduced_motion: bool

    def guidance(self) -> str:
        return (
            f"Runtime profile: {self.name}; {self.ram_gb:g} GB RAM; "
            f"at most {self.task_concurrency} background tool job(s). "
            "Use the configured AI provider; never download or start local models without a request. "
            "Keep important account workflows visible in the browser. Use background work for small "
            "independent research tasks; keep listening and accept new commands while these run. "
            "Shared mouse/keyboard operations remain serialized. Process media one job at a time, preserve originals, and "
            "report missing integrations or credentials instead of claiming an action succeeded. "
            "Do not promise universal app access or unattended trading."
        )


def profile_for_ram(ram_gb: float) -> RuntimeProfile:
    if ram_gb < 8:
        return RuntimeProfile("lightweight", round(ram_gb, 1), 1, 40, True)
    if ram_gb <= 16:
        return RuntimeProfile("lightweight", round(ram_gb, 1), 2, 40, True)
    return RuntimeProfile("standard", round(ram_gb, 1), 3, 100, False)


@lru_cache(maxsize=1)
def get_runtime_profile() -> RuntimeProfile:
    try:
        import psutil
        ram = psutil.virtual_memory().total / (1024 ** 3)
        if ram <= 0:
            raise ValueError("Invalid memory size")
    except Exception:
        # Conservative settings when a restricted environment hides hardware.
        ram = 12
    return profile_for_ram(ram)
