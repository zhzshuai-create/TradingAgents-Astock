# -*- coding: utf-8 -*-
"""统一线性图标（feather/lucide 同形）：24 viewBox、stroke=currentColor、fill=none。

只用于 HTML 语境（st.markdown / st.caption 的 unsafe_allow_html、iframe 内嵌 HTML）。
Streamlit 原生 widget 的 label 不吃 HTML——组件图标走 icon=":material/xxx:"
（st.toast / st.button 原生支持），widget 标签一律纯文本。
"""
from __future__ import annotations

_TPL = (
    '<svg class="app-ic" width="{s}" height="{s}" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
    'stroke-linejoin="round" style="vertical-align:-0.15em" '
    'aria-hidden="true">{body}</svg>'
)

_PATHS = {
    "bolt": '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
    "bar-chart": (
        '<line x1="6" y1="20" x2="6" y2="16"/><line x1="12" y1="20" x2="12" y2="10"/>'
        '<line x1="18" y1="20" x2="18" y2="4"/>'
    ),
    "monitor": (
        '<rect x="2" y="3" width="20" height="14" rx="2"/>'
        '<line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>'
    ),
    "candlestick": (
        '<path d="M8 6v2"/><rect x="6" y="8" width="4" height="7" rx="1"/>'
        '<path d="M8 15v3"/><path d="M16 3v2"/><rect x="14" y="5" width="4" height="7" rx="1"/>'
        '<path d="M16 12v5"/>'
    ),
    "message-circle": (
        '<path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 '
        '8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 '
        '8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>'
    ),
    "newspaper": (
        '<path d="M4 22h16a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v16'
        'a2 2 0 0 1-2 2Zm0 0a2 2 0 0 1-2-2v-9c0-1.1.9-2 2-2h2"/>'
        '<path d="M18 14h-8"/><path d="M15 18h-5"/><path d="M10 6h8v4h-8V6Z"/>'
    ),
    "clipboard-list": (
        '<rect x="8" y="2" width="8" height="4" rx="1"/>'
        '<path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6'
        'a2 2 0 0 1 2-2h2"/>'
        '<path d="M12 11h4"/><path d="M12 16h4"/><path d="M8 11h.01"/><path d="M8 16h.01"/>'
    ),
    "landmark": (
        '<line x1="3" y1="22" x2="21" y2="22"/><line x1="6" y1="18" x2="6" y2="11"/>'
        '<line x1="10" y1="18" x2="10" y2="11"/><line x1="14" y1="18" x2="14" y2="11"/>'
        '<line x1="18" y1="18" x2="18" y2="11"/><polygon points="12 2 20 7 4 7"/>'
    ),
    "flame": (
        '<path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3'
        '-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5'
        'a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z"/>'
    ),
    "lock": (
        '<rect x="3" y="11" width="18" height="11" rx="2"/>'
        '<path d="M7 11V7a5 5 0 0 1 10 0v4"/>'
    ),
    "briefcase": (
        '<rect x="2" y="7" width="20" height="14" rx="2"/>'
        '<path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/>'
    ),
}


def icon(name: str, size: int = 14) -> str:
    """返回内联 SVG 字符串；未知名字抛 KeyError（调用方写错应尽早暴露）。"""
    return _TPL.format(s=size, body=_PATHS[name])
