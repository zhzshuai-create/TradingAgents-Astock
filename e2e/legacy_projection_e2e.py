"""P3-08 R-08 / CMP-04: old Streamlit opens a projected report under a temp HOME.

The script projects a report-v1 DTO into ``<temp HOME>/.tradingagents/logs``,
checks the path depth ``web/history.py`` expects, then runs the old app through
Streamlit's AppTest with ``viewing_history`` pointed at that file. It never
reads or writes the real ``~/.tradingagents`` tree.

Run: "C:/Users/zhzsh/AppData/Local/Programs/Python/Python313/python.exe" e2e/legacy_projection_e2e.py
"""

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURE = ROOT / "tests" / "fixtures" / "upgrade" / "final_state_v1.json"
STRATEGY_DIR = "TradingAgentsStrategy_logs"

checks: list[tuple[str, bool]] = []


def check(name: str, condition: bool) -> None:
    checks.append((name, bool(condition)))
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")


def main() -> int:
    golden = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload = copy.deepcopy(golden)
    payload["sections"]["sec-plan"]["body"] = (
        "## 最终投资建议\n\nP3-08 投影正文。\n\n| 指标 | 值 |\n| --- | --- |\n| 样本 | 1 |"
    )
    payload["sections"]["sec-decision"]["body"] = (
        "## 最终交易决策\n\n**Rating**: Overweight\n\n**Signal**: Buy\n\nP3-08 投影正文。"
    )

    with tempfile.TemporaryDirectory(prefix="p3-08-e2e-") as raw:
        home = Path(raw) / "home"
        home.mkdir()
        os.environ["HOME"] = str(home)
        os.environ["USERPROFILE"] = str(home)

        from backend.app.services.legacy_projection import (
            PROJECTED,
            project_payload,
        )

        logs = home / ".tradingagents" / "logs"
        outcome = project_payload(payload, logs_root=logs)
        check("projection returns projected", outcome.status == PROJECTED)
        assert outcome.path is not None
        relative = outcome.path.relative_to(logs).parts
        check(
            "path matches web/history.py depth",
            relative
            == ("000629", STRATEGY_DIR, "full_states_log_2026-10-24.json"),
        )

        from web import history

        history._invalidate_history_cache()
        entries = history.get_history()
        check("old history lists the projected file", len(entries) == 1)
        check(
            "history entry carries ticker and date",
            bool(entries)
            and entries[0]["ticker"] == "000629"
            and entries[0]["date"] == "2026-10-24",
        )
        state = history.load_analysis(str(outcome.path))
        check("old loader reads the state dict", isinstance(state, dict))
        check("old signal scan returns Buy", history.extract_signal(state) == "Buy")

        import pandas as pd
        import web.data_functions as data_functions
        import web.journal_service as journal_service
        import web.pdf_export as pdf_export
        from streamlit.testing.v1 import AppTest
        from tradingagents.dataflows.a_stock import _common as astock_data

        class _NoTdx:
            def __getattr__(self, name):
                return lambda *args, **kwargs: None

        data_functions.index_spot = lambda: {}
        data_functions.tencent_quote = lambda codes: {}
        data_functions.start_bars_fuse_prewarm = lambda *args, **kwargs: None
        data_functions._get_kline_full = lambda code: pd.DataFrame()
        data_functions._tdx_client = lambda: _NoTdx()
        astock_data._get_mootdx_client = lambda: _NoTdx()
        astock_data._load_ohlcv_astock = lambda *args, **kwargs: pd.DataFrame()
        pdf_export.generate_pdf = lambda *args, **kwargs: b"%PDF-1.4\n"
        journal_service.start_journal = lambda: None

        app = AppTest.from_file(str(ROOT / "web" / "app.py"), default_timeout=120)
        app.session_state["viewing_history"] = str(outcome.path)
        app.run()
        check("old app renders without exception", not app.exception)
        rendered = "\n".join(str(item.value) for item in app.markdown)
        check("old app shows the projected body", "P3-08 投影正文" in rendered)
        check("old app shows the same rating", "Overweight" in rendered)
        check("old app shows the same Buy signal", "BUY" in rendered)
        check("old app shows the Chinese signal label", "买入" in rendered)
        check(
            "old app shows the investment-plan heading",
            "最终投资建议" in rendered,
        )

    failures = [name for name, ok in checks if not ok]
    print(f"\n{len(checks)} checks, {len(failures)} failures")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
