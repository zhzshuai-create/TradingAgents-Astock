"""P1-03 acceptance tests: config snapshot and resume fingerprint.

CFG-01 same content in a different key order hashes identically.
CFG-02 any field change changes the hash.
CFG-03 normalization rules are fixed and stable across processes and 100 runs.
CFG-04 resume requires both config hash and graph version to match.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.services.config_snapshot import (  # noqa: E402
    InvalidConfigValue,
    ResumeFingerprintMismatch,
    UnknownConfigKey,
    canonical_json,
    check_resume,
    config_hash,
    normalize_config,
    resume_fingerprint,
)

DEFAULTS = {
    "parallel_analysts": True,
    "stage_toggles": {"policy": True, "hot_money": True, "lockup": True},
}
GRAPH_VERSION = "fake-graph-v1"
BASE_CONFIG = {
    "llm_profile": "deepseek-default",
    "parallel_analysts": True,
    "stage_toggles": {"policy": True, "hot_money": True, "lockup": True},
}


def _hash(config, graph_version=GRAPH_VERSION):
    return config_hash(normalize_config(config, defaults=DEFAULTS), graph_version)


def test_cfg01_key_order_does_not_change_hash():
    reordered = {
        "stage_toggles": {"lockup": True, "policy": True, "hot_money": True},
        "parallel_analysts": True,
        "llm_profile": "deepseek-default",
    }
    assert _hash(BASE_CONFIG) == _hash(reordered)


def test_cfg01_omitted_defaults_equal_explicit_defaults():
    assert _hash({"llm_profile": "deepseek-default"}) == _hash(BASE_CONFIG)


def test_cfg02_any_field_change_changes_hash():
    base = _hash(BASE_CONFIG)
    variants = [
        {**BASE_CONFIG, "llm_profile": "openai-default"},
        {**BASE_CONFIG, "parallel_analysts": False},
        {
            **BASE_CONFIG,
            "stage_toggles": {"policy": False, "hot_money": True, "lockup": True},
        },
    ]
    variant_hashes = {_hash(variant) for variant in variants}
    assert len(variant_hashes) == 3
    assert base not in variant_hashes
    assert _hash(BASE_CONFIG, "fake-graph-v2") != base


def test_cfg03_canonical_json_rules_are_fixed():
    assert canonical_json({"b": 1.0, "a": None}) == '{"a":null,"b":1.0}'
    assert canonical_json(1) != canonical_json(1.0)
    assert canonical_json(True) != canonical_json(1)
    assert canonical_json(-0.0) == canonical_json(0.0)
    assert canonical_json([1, {"z": None}]) == '[1,{"z":null}]'


def test_cfg03_hash_is_stable_across_one_hundred_runs():
    assert len({_hash(BASE_CONFIG) for _ in range(100)}) == 1


def test_cfg03_hash_is_stable_across_processes():
    script = (
        "import json, sys\n"
        "from backend.app.services.config_snapshot import config_hash, normalize_config\n"
        "defaults = json.loads(sys.argv[1])\n"
        "config = json.loads(sys.argv[2])\n"
        "snapshot = normalize_config(config, defaults=defaults)\n"
        "print(config_hash(snapshot, sys.argv[3]))\n"
    )
    outputs = []
    for _ in range(2):
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                script,
                json.dumps(DEFAULTS),
                json.dumps(BASE_CONFIG),
                GRAPH_VERSION,
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        outputs.append(completed.stdout.strip())
    assert outputs[0] == outputs[1] == _hash(BASE_CONFIG)


def test_cfg04_resume_accepts_matching_fingerprint():
    snapshot = normalize_config(BASE_CONFIG, defaults=DEFAULTS)
    digest = config_hash(snapshot, GRAPH_VERSION)
    assert (
        check_resume(
            stored_config_hash=digest,
            stored_graph_version=GRAPH_VERSION,
            config=BASE_CONFIG,
            defaults=DEFAULTS,
            graph_version=GRAPH_VERSION,
        )
        == snapshot
    )


def test_cfg04_resume_rejects_config_drift():
    digest = _hash(BASE_CONFIG)
    with pytest.raises(ResumeFingerprintMismatch) as excinfo:
        check_resume(
            stored_config_hash=digest,
            stored_graph_version=GRAPH_VERSION,
            config={**BASE_CONFIG, "parallel_analysts": False},
            defaults=DEFAULTS,
            graph_version=GRAPH_VERSION,
        )
    assert excinfo.value.config_hash_mismatch is True
    assert excinfo.value.graph_version_mismatch is False


def test_cfg04_resume_rejects_graph_version_drift():
    digest = _hash(BASE_CONFIG)
    with pytest.raises(ResumeFingerprintMismatch) as excinfo:
        check_resume(
            stored_config_hash=digest,
            stored_graph_version=GRAPH_VERSION,
            config=BASE_CONFIG,
            defaults=DEFAULTS,
            graph_version="fake-graph-v2",
        )
    assert excinfo.value.config_hash_mismatch is True
    assert excinfo.value.graph_version_mismatch is True


def test_cfg04_fingerprint_covers_both_parts():
    digest = _hash(BASE_CONFIG)
    assert resume_fingerprint(digest, GRAPH_VERSION) == resume_fingerprint(
        digest, GRAPH_VERSION
    )
    assert resume_fingerprint(digest, GRAPH_VERSION) != resume_fingerprint(
        digest, "fake-graph-v2"
    )
    assert resume_fingerprint(digest, GRAPH_VERSION) != resume_fingerprint(
        _hash({**BASE_CONFIG, "parallel_analysts": False}), GRAPH_VERSION
    )


def test_normalize_rejects_unknown_keys_and_bad_values():
    with pytest.raises(UnknownConfigKey):
        normalize_config({**BASE_CONFIG, "api_key": "secret"}, defaults=DEFAULTS)
    with pytest.raises(UnknownConfigKey):
        normalize_config(
            {"llm_profile": "x", "stage_toggles": {"news": True}}, defaults=DEFAULTS
        )
    with pytest.raises(InvalidConfigValue):
        normalize_config({"llm_profile": "  "}, defaults=DEFAULTS)
    with pytest.raises(InvalidConfigValue):
        normalize_config({**BASE_CONFIG, "parallel_analysts": "yes"}, defaults=DEFAULTS)
    with pytest.raises(InvalidConfigValue):
        normalize_config(
            {"llm_profile": "x", "stage_toggles": {"policy": "yes"}}, defaults=DEFAULTS
        )
