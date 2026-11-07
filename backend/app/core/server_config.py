"""Server-owned settings that clients may not submit (api-v1.md 1.3).

The stage-toggle key list lives here, not in config_snapshot, so normalization
never hardcodes which stages exist. P2 replaces this module's defaults with the
meta/options source without touching the hashing rules.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from backend.app.core.write_mode import (
    DEFAULT_WRITE_MODE,
    WRITE_MODE_ENV,
    parse_write_mode,
)

DEFAULT_LLM_PROFILE = "deepseek-default"
DEFAULT_STAGE_TOGGLES: dict[str, bool] = {
    "policy": True,
    "hot_money": True,
    "lockup": True,
}


@dataclass(frozen=True)
class ServerConfig:
    graph_version: str = "graph-v1"
    llm_profiles: tuple[str, ...] = (DEFAULT_LLM_PROFILE,)
    parallel_analysts: bool = True
    stage_toggles: dict[str, bool] = field(
        default_factory=lambda: dict(DEFAULT_STAGE_TOGGLES)
    )
    real_runner_enabled: bool = False
    write_mode: str = DEFAULT_WRITE_MODE

    def config_defaults(self) -> dict:
        return {
            "parallel_analysts": self.parallel_analysts,
            "stage_toggles": dict(self.stage_toggles),
        }


def load_server_config() -> ServerConfig:
    profiles = tuple(
        item.strip()
        for item in os.environ.get("TA_LLM_PROFILES", DEFAULT_LLM_PROFILE).split(",")
        if item.strip()
    )
    return ServerConfig(
        graph_version=os.environ.get("TA_GRAPH_VERSION", "graph-v1"),
        llm_profiles=profiles or (DEFAULT_LLM_PROFILE,),
        write_mode=parse_write_mode(os.environ.get(WRITE_MODE_ENV)),
    )
