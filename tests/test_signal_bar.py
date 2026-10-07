"""历史信号分布条 builder（stock_display.signal_bar_html）的单测.

覆盖: 常规三段(段内图例)/零段跳过/窄段只留悬停/空态只留轨道.
纯函数无 IO, 离线可重复.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def test_signal_bar_wide_segments_embed_labels():
    from web.stock_display import signal_bar_html

    h = signal_bar_html(12, 4, 3)
    assert 'class="sig-bar"' in h
    for cls, label, n in (("sig-seg--buy", "买入", 12),
                          ("sig-seg--hold", "持有", 4),
                          ("sig-seg--sell", "卖出", 3)):
        seg = h.split(cls, 1)[1].split("</div>", 1)[0]
        assert f"{label} {n}" in seg          # 段内图例
        assert f'title="{label} {n}"' in h    # 悬停兜底
    assert "flex:12" in h and "flex:4" in h and "flex:3" in h


def test_signal_bar_narrow_segment_hides_inline_label():
    from web.stock_display import signal_bar_html

    h = signal_bar_html(49, 0, 1)  # 卖出 1/50 = 2% → 段内放不下图例
    assert "sig-seg--sell" in h
    assert 'title="卖出 1"' in h
    assert ">卖出 1<" not in h            # 图例只存在于 title, 不内嵌
    assert "sig-seg--hold" not in h       # 零段不渲染


def test_signal_bar_zero_counts_and_empty():
    from web.stock_display import signal_bar_html

    only_buy = signal_bar_html(10, 0, 0)
    assert "sig-seg--buy" in only_buy and "sig-seg--hold" not in only_buy

    empty = signal_bar_html(0, 0, 0)
    assert empty == '<div class="sig-bar"></div>'  # 空态只留轨道, 不留空洞
