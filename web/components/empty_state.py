"""统一的空状态占位：图标 + 标题 + 一句说明。

替代散落的 st.caption/st.warning 纯文字，保证「没有数据」在任何面板里
都是同一种视觉表达（见 theme.py `.empty-state`）。
"""

from __future__ import annotations

import html

import streamlit as st

_ICON_SVG = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" '
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M4 19V5"/><path d="M4 19h16"/>'
    '<rect x="7" y="11" width="3" height="5" rx="0.6"/>'
    '<rect x="12" y="7" width="3" height="9" rx="0.6"/>'
    '<rect x="17" y="13" width="3" height="3" rx="0.6"/>'
    "</svg>"
)


def empty_state_html(title: str, hint: str = "") -> str:
    hint_html = f'<div class="empty-hint">{html.escape(hint)}</div>' if hint else ""
    return (
        f'<div class="empty-state"><div class="empty-icon">{_ICON_SVG}</div>'
        f'<div class="empty-title">{html.escape(title)}</div>{hint_html}</div>'
    )


def render_empty_state(title: str, hint: str = "") -> None:
    st.markdown(empty_state_html(title, hint), unsafe_allow_html=True)
