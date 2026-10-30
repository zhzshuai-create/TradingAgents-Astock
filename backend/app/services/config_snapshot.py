"""Configuration snapshots and fingerprints for the job kernel.

The hash must be identical in every process, so normalization is explicit:
whitelist the three contract keys, fill server defaults, then serialize with
sorted keys and fixed separators. graph_version is part of the hash because the
contract defines config_hash as the hash of model config, stage toggles and
graph version together (idempotency-conflicts.md section 1).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

CONFIG_KEYS = ("llm_profile", "parallel_analysts", "stage_toggles")


class ConfigError(ValueError):
    """Base class for configuration errors; P1-04 maps these to 422 codes."""


class UnknownConfigKey(ConfigError):
    def __init__(self, key: str) -> None:
        super().__init__(f"unknown config key: {key}")
        self.key = key


class InvalidConfigValue(ConfigError):
    def __init__(self, field: str, value: Any) -> None:
        super().__init__(f"invalid config value for {field}: {value!r}")
        self.field = field
        self.value = value


class ResumeFingerprintMismatch(Exception):
    def __init__(self, *, config_hash_mismatch: bool, graph_version_mismatch: bool) -> None:
        super().__init__(
            "resume fingerprint mismatch: "
            f"config_hash={config_hash_mismatch}, graph_version={graph_version_mismatch}"
        )
        self.config_hash_mismatch = config_hash_mismatch
        self.graph_version_mismatch = graph_version_mismatch


def normalize_config(
    config: Mapping[str, Any], *, defaults: Mapping[str, Any]
) -> dict[str, Any]:
    """Return the canonical snapshot stored in jobs.config_snapshot."""
    unknown = sorted(set(config) - set(CONFIG_KEYS))
    if unknown:
        raise UnknownConfigKey(unknown[0])

    profile = config.get("llm_profile")
    if not isinstance(profile, str) or not profile.strip():
        raise InvalidConfigValue("llm_profile", profile)

    parallel = config.get("parallel_analysts", defaults.get("parallel_analysts"))
    if not isinstance(parallel, bool):
        raise InvalidConfigValue("parallel_analysts", parallel)

    toggle_defaults = defaults.get("stage_toggles", {})
    if not isinstance(toggle_defaults, Mapping):
        raise InvalidConfigValue("stage_toggles", toggle_defaults)
    raw_toggles = config.get("stage_toggles", {})
    if not isinstance(raw_toggles, Mapping):
        raise InvalidConfigValue("stage_toggles", raw_toggles)

    unknown_toggles = sorted(set(raw_toggles) - set(toggle_defaults))
    if unknown_toggles:
        raise UnknownConfigKey(f"stage_toggles.{unknown_toggles[0]}")
    for key, value in raw_toggles.items():
        if not isinstance(value, bool):
            raise InvalidConfigValue(f"stage_toggles.{key}", value)

    return {
        "llm_profile": profile,
        "parallel_analysts": parallel,
        "stage_toggles": {
            key: bool(raw_toggles.get(key, default))
            for key, default in toggle_defaults.items()
        },
    }


def canonical_json(value: Any) -> str:
    return json.dumps(
        _canonical(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _canonical(value: Any) -> Any:
    if isinstance(value, Mapping):
        result = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"config keys must be strings, got {type(key).__name__}")
            result[key] = _canonical(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("config floats must be finite")
        # -0.0 and 0.0 are the same value; keep one spelling for a stable hash.
        return 0.0 if value == 0 else value
    if isinstance(value, (bool, int, str)) or value is None:
        return value
    raise TypeError(f"unsupported config value type: {type(value).__name__}")


def config_hash(snapshot: Mapping[str, Any], graph_version: str) -> str:
    if not isinstance(graph_version, str) or not graph_version:
        raise InvalidConfigValue("graph_version", graph_version)
    payload = {"config": snapshot, "graph_version": graph_version}
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def resume_fingerprint(config_digest: str, graph_version: str) -> str:
    payload = {"config_hash": config_digest, "graph_version": graph_version}
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def check_resume(
    *,
    stored_config_hash: str,
    stored_graph_version: str,
    config: Mapping[str, Any],
    defaults: Mapping[str, Any],
    graph_version: str,
) -> dict[str, Any]:
    """Validate a resume request; raises ResumeFingerprintMismatch on drift."""
    snapshot = normalize_config(config, defaults=defaults)
    current_hash = config_hash(snapshot, graph_version)
    config_hash_mismatch = current_hash != stored_config_hash
    graph_version_mismatch = graph_version != stored_graph_version
    if config_hash_mismatch or graph_version_mismatch:
        raise ResumeFingerprintMismatch(
            config_hash_mismatch=config_hash_mismatch,
            graph_version_mismatch=graph_version_mismatch,
        )
    return snapshot
