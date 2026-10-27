from __future__ import annotations

import pandas as pd
from streamlit.testing.v1 import AppTest


def test_hot_stock_external_text_is_escaped(monkeypatch):
    import web.components.data_dashboard as dash

    payload = "<img src=x onerror=alert(1)>"
    hot = pd.DataFrame([{
        "代码": "002694",
        "名称": payload,
        "涨幅%": 1.0,
        "题材归因": f"{payload}+军工",
    }])
    monkeypatch.setattr(dash, "ths_hot_reason", lambda *args, **kwargs: hot)
    at = AppTest.from_string(
        "from web.components.data_dashboard import render_data_mode\n"
        "render_data_mode()\n",
        default_timeout=120,
    )
    at.session_state["dash_tab"] = "强势股归因"
    at.run()

    assert not at.exception
    markdown = [element.value for element in at.markdown]
    assert any("&lt;img src=x onerror=alert(1)&gt;" in value for value in markdown)
    assert all(payload not in value for value in markdown)
