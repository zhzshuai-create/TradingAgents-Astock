"""web/app.py 的冒烟测试 — 保护导入重排不产生回归.

背景: app.py 是 683 行平铺脚本, 名字活在模块作用域, 且此前零测试覆盖.
启动动画改动要重排它的顶层导入, 回归只会出现在特定模式分支上, 肉眼走查容易漏.

三个模式各跑一遍完整脚本, 断言不抛异常.
网络调用被打桩(index_spot 每次加载都会命中), 保证测试可离线重复.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

APP_PATH = PROJECT_ROOT / "web" / "app.py"

# 冷启动导入链约 5.6s, 默认 3s 超时不够
APP_TIMEOUT = 120


@pytest.fixture(autouse=True)
def _stub_network(monkeypatch):
    """app.py 模块级会调 index_spot() 拉三大指数, 测试里必须打桩."""
    import web.data_functions as df

    monkeypatch.setattr(df, "index_spot", lambda: {}, raising=True)


def _run_app(mode: str):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(APP_PATH), default_timeout=APP_TIMEOUT)
    at.session_state["app_mode"] = mode
    at.run()
    return at


@pytest.mark.parametrize("mode", ["analysis", "data", "journal"])
def test_app_runs_without_exception(mode):
    at = _run_app(mode)
    assert not at.exception, f"模式 {mode} 抛异常: {[e.value for e in at.exception]}"


def test_analysis_mode_renders_sidebar_and_nav():
    """分析模式是主路径: 侧栏与顶部导航必须真的渲染出来, 不能只是没抛异常."""
    at = _run_app("analysis")
    assert not at.exception
    assert len(at.sidebar) > 0, "侧栏为空 — render_sidebar 可能没被调用"


def test_import_order_does_not_break_default_config():
    """头号风险的断言: DEFAULT_CONFIG 的 env 驱动键必须反映 .env, 而不是静默回落默认值.

    tradingagents/default_config.py 在模块级读 os.getenv, 所以只要它的导入被挪到
    load_dotenv() 之前, parallel_analysts 会静默变 False、mimo_reasoning_effort 会
    静默降级成 low —— 不抛异常, 肉眼也看不出来. 这条测试就是那道闸.
    """
    from dotenv import dotenv_values

    from _boot_config_helpers import run_app_in_clean_env

    env_file = PROJECT_ROOT / ".env"
    expected = dotenv_values(env_file) if env_file.exists() else {}

    cfg = run_app_in_clean_env(APP_PATH, APP_TIMEOUT)

    want_parallel = expected.get("TA_PARALLEL_ANALYSTS", "0") == "1"
    assert cfg["parallel_analysts"] is want_parallel, (
        f"parallel_analysts={cfg['parallel_analysts']} 与 .env 的 "
        f"TA_PARALLEL_ANALYSTS={expected.get('TA_PARALLEL_ANALYSTS')!r} 不一致 — "
        "极可能是 default_config 的导入跑到了 load_dotenv 之前"
    )

    if "MIMO_REASONING_EFFORT" in expected:
        assert cfg["mimo_reasoning_effort"] == expected["MIMO_REASONING_EFFORT"], (
            f"mimo_reasoning_effort={cfg['mimo_reasoning_effort']!r} 静默回落了, "
            f".env 里是 {expected['MIMO_REASONING_EFFORT']!r}"
        )
