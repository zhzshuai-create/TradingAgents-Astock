"""Web 侧栏 LLM 配置持久化：位置、恢复、不覆盖当次修改、写失败不打断。"""

from __future__ import annotations

import json
import logging
import types
from pathlib import Path

import pytest

from web.components import sidebar


@pytest.fixture()
def fake_st(monkeypatch, tmp_path):
    st = types.SimpleNamespace(session_state={})
    monkeypatch.setattr(sidebar, "st", st)
    monkeypatch.setattr(
        sidebar,
        "_LLM_CONFIG_PATH",
        tmp_path / "home" / ".tradingagents" / "llm_config.json",
    )
    return st


@pytest.mark.unit
def test_config_file_lives_under_user_home():
    assert sidebar._DEFAULT_LLM_CONFIG_PATH.parent.name == ".tradingagents"
    assert "site-packages" not in str(sidebar._DEFAULT_LLM_CONFIG_PATH)


@pytest.mark.unit
def test_save_creates_parent_and_roundtrips_model_ids(fake_st):
    fake_st.session_state.update(
        {
            "llm_provider": "deepseek",
            "quick_think_llm": "deepseek-chat",
            "deep_think_llm": "deepseek-reasoner",
            "llm_base_url": "https://relay.example/v1",
            "parallel_analysts": True,
            "custom_quick_model": "my-q",
        }
    )
    sidebar._save_llm_config()

    saved = json.loads(sidebar._LLM_CONFIG_PATH.read_text(encoding="utf-8"))
    assert saved["llm_provider"] == "deepseek"
    assert saved["quick_think_llm"] == "deepseek-chat"
    assert saved["deep_think_llm"] == "deepseek-reasoner"
    assert saved["parallel_analysts"] is True

    fake_st.session_state.clear()
    sidebar._load_saved_llm_config()
    ss = fake_st.session_state
    assert ss["llm_provider_idx"] == sidebar._PROVIDER_KEYS.index("deepseek")
    assert ss["llm_base_url"] == "https://relay.example/v1"
    assert ss["parallel_analysts"] is True
    assert ss["custom_quick_model"] == "my-q"


@pytest.mark.unit
def test_saved_model_index_resolves_by_id_not_position():
    saved = {"llm_provider": "deepseek", "quick_think_llm": "deepseek-chat"}
    assert sidebar._saved_model_index(
        saved, "deepseek", "quick_think_llm", ["a", "deepseek-chat"]
    ) == 1
    # 供应商变了或模型已下架时回到首项，不能沿用别的供应商的索引
    assert sidebar._saved_model_index(
        saved, "mimo", "quick_think_llm", ["a", "deepseek-chat"]
    ) == 0
    assert sidebar._saved_model_index(
        saved, "deepseek", "quick_think_llm", ["a"]
    ) == 0


@pytest.mark.unit
def test_load_does_not_override_current_session_choice(fake_st):
    sidebar._LLM_CONFIG_PATH.parent.mkdir(parents=True)
    sidebar._LLM_CONFIG_PATH.write_text(
        json.dumps(
            {
                "llm_provider": "openai",
                "llm_base_url": "https://saved.example/v1",
                "parallel_analysts": True,
            }
        ),
        encoding="utf-8",
    )
    fake_st.session_state.update(
        {
            "llm_provider_idx": 0,
            "llm_base_url": "https://current.example/v1",
            "parallel_analysts": False,
        }
    )

    sidebar._load_saved_llm_config()

    assert fake_st.session_state["llm_provider_idx"] == 0
    assert fake_st.session_state["llm_base_url"] == "https://current.example/v1"
    assert fake_st.session_state["parallel_analysts"] is False


@pytest.mark.unit
def test_unknown_provider_keeps_widget_default(fake_st):
    sidebar._LLM_CONFIG_PATH.parent.mkdir(parents=True)
    sidebar._LLM_CONFIG_PATH.write_text(
        json.dumps({"llm_provider": "gone"}), encoding="utf-8"
    )

    sidebar._load_saved_llm_config()

    assert "llm_provider_idx" not in fake_st.session_state


@pytest.mark.unit
def test_unchanged_config_does_not_rewrite_file(fake_st, monkeypatch):
    fake_st.session_state.update(
        {"llm_provider": "deepseek", "quick_think_llm": "deepseek-chat"}
    )
    sidebar._save_llm_config()

    writes = []
    original = Path.write_text

    def counting(self, *args, **kwargs):
        writes.append(self)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", counting)
    sidebar._save_llm_config()
    assert writes == []


@pytest.mark.unit
def test_write_failure_only_warns(fake_st, caplog):
    caplog.set_level(logging.WARNING)
    # 父目录位置被普通文件占住 → mkdir 抛 OSError；持久化失败不得冒泡
    blocker = sidebar._LLM_CONFIG_PATH.parent.parent
    blocker.write_text("not a dir", encoding="utf-8")
    fake_st.session_state["llm_provider"] = "deepseek"

    sidebar._save_llm_config()

    assert any("持久化失败" in record.getMessage() for record in caplog.records)
