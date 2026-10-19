"""统一空状态与报告正文排版的测试。"""

from __future__ import annotations

from pathlib import Path

from web.components.empty_state import empty_state_html

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_empty_state_html_contains_structure():
    markup = empty_state_html("暂无K线数据", "行情源暂不可用")

    assert 'class="empty-state"' in markup
    assert 'class="empty-title"' in markup
    assert 'class="empty-hint"' in markup
    assert "<svg" in markup


def test_empty_state_escapes_user_text():
    markup = empty_state_html('<script>alert(1)</script>', 'a & b')

    assert "<script>" not in markup
    assert "&lt;script&gt;" in markup
    assert "a &amp; b" in markup


def test_empty_state_css_and_report_prose_tokens_exist():
    from web.theme import CSS

    assert ".empty-state" in CSS
    assert ".empty-state .empty-hint" in CSS
    assert ".st-key-report_prose" in CSS
    assert ".st-key-report_prose blockquote" in CSS


def test_dashboard_uses_shared_empty_state():
    source = (PROJECT_ROOT / "web" / "components" / "data_dashboard.py").read_text(encoding="utf-8")

    assert "render_empty_state" in source
    assert 'st.caption("暂无' not in source
    assert 'st.warning("暂无' not in source


def test_report_viewer_uses_prose_container_and_empty_state():
    source = (PROJECT_ROOT / "web" / "components" / "report_viewer.py").read_text(encoding="utf-8")

    assert 'st.container(key="report_prose")' in source
    assert "_render_report_block" in source
    assert '"无数据"' not in source
