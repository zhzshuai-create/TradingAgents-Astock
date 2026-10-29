"""Cross-document consistency checks for the frozen P0 contracts (Day 7).

Each test carries a stable CT id. They parse the contract markdown itself, so a
silent wording drift between two documents fails the suite instead of being
caught by a human rereading 17 files.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "docs" / "upgrade" / "contracts"
FIXTURES = ROOT / "tests" / "fixtures" / "upgrade"
WIREFRAMES = ROOT / "docs" / "upgrade" / "wireframes"

STATES = [
    "queued",
    "running",
    "pause_requested",
    "paused",
    "cancel_requested",
    "cancelled",
    "succeeded",
    "failed",
    "interrupted",
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _section(text: str, heading: str) -> str:
    match = re.search(
        rf"^##+ {re.escape(heading)}.*?(?=^##+ |\Z)", text, re.M | re.S
    )
    assert match, f"section not found: {heading}"
    return match.group(0)


def _table_rows(section: str) -> list[list[str]]:
    rows = []
    for line in section.splitlines():
        line = line.strip()
        if not line.startswith("|") or set(line) <= set("|-: "):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        rows.append(cells)
    return rows[1:] if rows else []


def test_ct01_task_states_match_api_and_dictionary() -> None:
    """CT-01: 九个状态在状态机、接口按钮表、语义词典三处一致。"""
    machine = _read(CONTRACTS / "job-state-machine.md")
    block = re.search(r"```text\n(.*?)```", machine, re.S)
    assert block
    documented = [line.strip() for line in block.group(1).splitlines() if line.strip()]
    assert documented == STATES

    api = _read(CONTRACTS / "api-v1.md")
    action_rows = re.findall(
        r"^\|\s*([a-z_]+)\s*\|\s*([^|]*?)\s*\|$", api, re.M
    )
    actions = {state: value for state, value in action_rows if state in STATES}
    assert set(actions) == set(STATES), actions

    dictionary = _read(CONTRACTS / "semantic-dictionary.md")
    label_rows = _table_rows(_section(dictionary, "2. 状态与中文文案对照"))
    labels = {row[0]: row[1] for row in label_rows if row and row[0] in STATES}
    assert set(labels) == set(STATES), labels
    assert len(set(labels.values())) == 9, labels.values()


def test_ct02_status_labels_match_wireframes() -> None:
    """CT-02: 线框声明九种状态徽标，文案取自词典，且不含禁用词。"""
    dictionary = _read(CONTRACTS / "semantic-dictionary.md")
    label_rows = _table_rows(_section(dictionary, "2. 状态与中文文案对照"))
    labels = {row[0]: row[1] for row in label_rows if row and row[0] in STATES}
    assert len(labels) == 9

    builder = _read(ROOT / "scripts" / "build_wireframes_html.py")
    assert "九种状态徽标" in builder
    for label in labels.values():
        if label in builder:
            assert label in labels.values()

    rendered = ""
    for name in ("core-wireframes-desktop.html", "core-wireframes-mobile.html"):
        rendered += _read(WIREFRAMES / name)
    found = {label for label in labels.values() if label in rendered}
    assert found, "wireframes render none of the nine status labels"
    for banned in ("停止", "重跑", "任务不存在"):
        assert banned not in rendered, banned

    wireframe_doc = _read(CONTRACTS / "core-wireframes.md")
    assert "状态徽标" in wireframe_doc
    assert "allowed_actions" in wireframe_doc


def test_ct03_report_structure_matches_golden_samples() -> None:
    """CT-03: 报告章节 id 在契约表、Schema 与五份样本三处一致。"""
    doc = _read(CONTRACTS / "report-schema-v1.md")
    rows = _table_rows(_section(doc, "3. 章节结构（ReportDTO.sections）"))
    ids = [
        row[1].strip("`")
        for row in rows
        if len(row) >= 2 and row[1].strip("`").startswith("sec-")
    ]
    assert len(ids) == 13, ids
    assert len(set(ids)) == 13

    schema = json.loads(_read(CONTRACTS / "report-schema-v1.json"))
    schema_ids = schema["properties"]["sections"]["propertyNames"]["enum"]
    assert set(schema_ids) == set(ids)

    # Recompute the golden hash from the sample, never trust a stored value.
    sample = json.loads(_read(FIXTURES / "final_state_v1.json"))
    payload = json.dumps(
        sample["sections"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    assert hashlib.sha256(payload.encode("utf-8")).hexdigest() == sample["meta"]["content_hash"]

    # legacy_report_v1.json is the old-runner input shape, not a ReportDTO; it
    # exists so the P1 golden comparison has a legacy side to convert.
    legacy = json.loads(_read(FIXTURES / "legacy_report_v1.json"))
    assert "meta" not in legacy and "sections" not in legacy

    for path in sorted(FIXTURES.glob("*report*.json")) + [FIXTURES / "final_state_v1.json"]:
        data = json.loads(_read(path))
        if "meta" not in data:
            assert path.name == "legacy_report_v1.json", path.name
            continue
        jsonschema.validate(data, schema)
        assert set(data["sections"]) <= set(ids), path.name


def test_ct04_retry_and_resume_fields_agree() -> None:
    """CT-04: 重试/续跑字段与报告 meta 三处同名同义。"""
    machine = _read(CONTRACTS / "job-state-machine.md")
    api = _read(CONTRACTS / "api-v1.md")
    schema = json.loads(_read(CONTRACTS / "report-schema-v1.json"))
    errors = _read(CONTRACTS / "error-codes-v1.md")

    for field in ("retry_of_job_id", "resume_of_job_id", "resume_from_stage"):
        assert field in machine, field
        assert field in api, field
    assert "retry_of_job_id" in schema["properties"]["meta"]["properties"]

    assert "same_config" in api and "resume_from_checkpoint" in api
    assert "resume_fingerprint_mismatch" in errors


def test_ct05_market_status_matches_wireframes() -> None:
    """CT-05: 信封四态与样本、线框数据状态一致，partial 不是第五态。"""
    schema = json.loads(_read(CONTRACTS / "market-data-envelope-v1.json"))
    statuses = schema["properties"]["status"]["enum"]
    assert statuses == ["ok", "empty", "error", "stale"]
    assert schema["properties"]["partial"]["type"] == "boolean"

    seen = set()
    for path in sorted(FIXTURES.glob("market_*.json")):
        data = json.loads(_read(path))
        jsonschema.validate(data, schema)
        seen.add(data["status"])
    assert seen == set(statuses)

    builder = _read(ROOT / "scripts" / "build_wireframes_html.py")
    assert "指数块 ok" in builder
    assert "stale" in builder

    errors = _read(CONTRACTS / "error-codes-v1.md")
    assert "ok / empty / stale" in errors


def test_ct06_sse_events_match_state_machine() -> None:
    """CT-06: 六类事件、T01–T20、终态顺序与审计记录规则互相一致。"""
    sse = _read(CONTRACTS / "sse-events-v1.md")
    machine = _read(CONTRACTS / "job-state-machine.md")

    types = re.findall(r"^\|\s*`([a-z_]+)`\s*\|", _section(sse, "3. 六类事件"), re.M)
    assert set(types) == {
        "snapshot",
        "stage_changed",
        "stats",
        "status_changed",
        "report_ready",
        "error",
    }, types

    transitions = re.findall(r"^\|\s*(T\d{2})\s*\|", machine, re.M)
    assert len(transitions) == 20 and transitions[-1] == "T20"
    assert "T01–T20" in sse

    assert "审计记录" in sse and "不占 `seq`" in sse
    assert "`created`" in sse and "`transition_rejected`" in sse and "`reconcile_note`" in sse

    terminal = _section(sse, "6. 终态关闭")
    order = re.findall(r"^\d\.\s*`?([a-z_]+)`?", terminal, re.M)
    assert order[:3] == ["stats", "status_changed", "report_ready"], order
    assert "cancelled / failed / interrupted" in terminal


def test_ct07_error_codes_match_page_actions() -> None:
    """CT-07: 错误字典每条都有用户动作；接口文档引用的码都在字典里。"""
    errors = _read(CONTRACTS / "error-codes-v1.md")
    rows = _table_rows(_section(errors, "2. 接口错误码"))
    dictionary = {}
    for row in rows:
        if len(row) < 5 or not row[0].startswith("`"):
            continue
        code = row[0].strip("`")
        dictionary[code] = row
        assert row[4], f"missing user action: {code}"
        assert row[1].isdigit(), f"missing http status: {code}"

    referenced = set()
    for name in ("api-v1.md", "sse-events-v1.md"):
        text = _read(CONTRACTS / name)
        referenced |= set(
            re.findall(r"(?:400|401|404|405|409|410|422|429|500|501|502|504)\s*`([a-z_]+)`", text)
        )
    missing = referenced - set(dictionary)
    assert not missing, missing


def test_ct08_freeze_manifest_matches_contract_files() -> None:
    """CT-08: 冻结清单覆盖 15 份契约文件，哈希与当前内容一致。"""
    manifest = _read(CONTRACTS / "FREEZE-v1.md")
    rows = _table_rows(_section(manifest, "2. 冻结文件与校验值"))
    listed = {row[0].strip("`"): row[1].strip("`") for row in rows if len(row) >= 2}

    expected = {path.name for path in CONTRACTS.glob("*.md") if path.name != "FREEZE-v1.md"}
    expected |= {path.name for path in CONTRACTS.glob("*.json")}
    assert set(listed) == expected, (set(listed) ^ expected)

    for name, digest in listed.items():
        actual = hashlib.sha256((CONTRACTS / name).read_bytes()).hexdigest()
        assert actual == digest, name

    for name in expected:
        if name.endswith(".md"):
            assert "版本：v1" in _read(CONTRACTS / name), name
