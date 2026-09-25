"""在干净环境里跑一次 app.py, 取回它实际看到的 DEFAULT_CONFIG.

为什么用子进程: 这个检查要求 tradingagents.default_config 尚未被导入、且相关环境变量
尚未进入 os.environ —— 只有这样 app.py 自己的 load_dotenv() 才是唯一能设置它们的途径,
导入顺序错误才会暴露. 在 pytest 进程里做这件事会污染同一 session 的其他测试
(sys.modules 与 os.environ 都是全局的), 所以整个检查隔离到子进程.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

# default_config.py 在模块级读这些键; 检查前必须把它们从环境里抹掉
ENV_DRIVEN_KEYS = (
    "TA_PARALLEL_ANALYSTS",
    "MIMO_REASONING_EFFORT",
    "TRADINGAGENTS_RESULTS_DIR",
    "TRADINGAGENTS_CACHE_DIR",
    "TRADINGAGENTS_MEMORY_LOG_PATH",
)

CONFIG_KEYS = (
    "parallel_analysts",
    "mimo_reasoning_effort",
    "results_dir",
    "data_cache_dir",
    "memory_log_path",
)

_CHILD = r"""
import json, os, sys
for k in %(env_keys)r:
    os.environ.pop(k, None)
for m in [m for m in list(sys.modules) if m.startswith("tradingagents")]:
    del sys.modules[m]

import web.data_functions as df
df.index_spot = lambda: {}

from streamlit.testing.v1 import AppTest
at = AppTest.from_file(%(app)r, default_timeout=%(timeout)d)
at.session_state["app_mode"] = "analysis"
at.run()
if at.exception:
    print(json.dumps({"error": [str(e.value) for e in at.exception]}))
    sys.exit(0)

from tradingagents.default_config import DEFAULT_CONFIG
print(json.dumps({k: DEFAULT_CONFIG.get(k) for k in %(cfg_keys)r}))
"""


def run_app_in_clean_env(app_path: Path, timeout: int = 120) -> dict:
    """跑一次 app.py, 返回它看到的 DEFAULT_CONFIG 中 env 驱动的键."""
    script = _CHILD % {
        "env_keys": list(ENV_DRIVEN_KEYS),
        "app": str(app_path),
        "timeout": timeout,
        "cfg_keys": list(CONFIG_KEYS),
    }
    env = {k: v for k, v in os.environ.items() if k not in ENV_DRIVEN_KEYS}
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(app_path.parent.parent),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout + 120,
    )
    out = (proc.stdout or "").strip().splitlines()
    if not out:
        raise AssertionError(
            f"子进程没有输出. exit={proc.returncode}\nstderr:\n{proc.stderr[-2000:]}"
        )
    data = json.loads(out[-1])
    if "error" in data:
        raise AssertionError(f"app.py 在干净环境下抛异常: {data['error']}")
    return data
