"""指标卡迷你走势图与卡片样式令牌的测试。"""

from __future__ import annotations

import re

from web.components.data_dashboard import _sparkline_svg


def test_sparkline_needs_two_valid_points():
    assert _sparkline_svg([]) == ""
    assert _sparkline_svg([10.0]) == ""
    assert _sparkline_svg([10.0, float("nan")]) == ""


def test_sparkline_skips_nan_and_maps_range():
    svg = _sparkline_svg([10.0, float("nan"), 12.0, 11.0], width=100, height=30)
    match = re.search(r'<polyline class="spark-line" points="([^"]+)"', svg)

    assert match is not None
    pts = match.group(1).split()
    xs = [float(p.split(",")[0]) for p in pts]
    ys = [float(p.split(",")[1]) for p in pts]

    assert xs == [0.0, 50.0, 100.0]
    assert ys == [28.0, 2.0, 15.0]  # 最低贴底(28)、最高贴顶(2)、中间等比
    assert 'class="spark-area"' in svg
    assert 'preserveAspectRatio="none"' in svg


def test_sparkline_flat_series_does_not_divide_by_zero():
    svg = _sparkline_svg([5.0, 5.0, 5.0])

    assert "polyline" in svg
    assert "nan" not in svg.lower()


def test_metric_card_css_uses_theme_tokens():
    from web.theme import CSS

    assert "--up-soft" in CSS and "--down-soft" in CSS
    assert ".metric-card .chip.up" in CSS
    assert ".metric-card.up .spark-line" in CSS
