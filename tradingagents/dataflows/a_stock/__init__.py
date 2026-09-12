"""A-stock (China mainland) data vendor for TradingAgents.

Zero third-party data dependency (no akshare). All sources are direct HTTP APIs
or mootdx TCP.

Data sources:
- mootdx (TCP 7709): OHLCV K-lines, financial snapshots, F10 text
- Tencent Finance (HTTP GBK): PE/PB/market cap/turnover
- 东方财富 push2 / datacenter-web (direct HTTP): stock info, dragon-tiger, lockup
- 新浪财经 (direct HTTP): K-line fallback, financial statements
- 同花顺 (direct HTTP): consensus EPS, hot stocks, northbound capital flow
- 财联社 (direct HTTP): global news wire

Submodules (split from the former monolithic a_stock.py):
- _common: shared infrastructure (ticker resolution, mootdx client, throttled
  东财 HTTP, 腾讯/同花顺/新浪 helpers, OHLCV cache + Sina supplement chain)
- quote: get_stock_data / get_indicators
- fundamentals: get_fundamentals / financial statements / get_profit_forecast /
  get_insider_transactions
- news: get_news / get_global_news
- signals: get_hot_stocks / get_northbound_flow / get_concept_blocks /
  get_fund_flow / get_dragon_tiger_board / get_lockup_expiry /
  get_industry_comparison

Every public and previously-importable private name is re-exported here, so
``from tradingagents.dataflows.a_stock import X`` keeps working unchanged.
"""

from ._common import *  # noqa: F401,F403
from ._common import (  # noqa: F401 — private helpers kept importable for backward compat
    _build_name_code_map,
    _get_prefix,
    _normalize_ticker,
    _get_mootdx_client,
    _tencent_quote,
    _UA,
    _DATACENTER_URL,
    _em_get,
    _eastmoney_datacenter,
    _ths_eps_forecast,
    _sina_kline_fallback,
    _last_ohlcv_date,
    _normalize_ohlcv_dates,
    _needs_sina_supplement,
    _merge_ohlcv,
    _supplement_stale_ohlcv_with_sina,
    _load_ohlcv_astock,
)
from .quote import *  # noqa: F401,F403
from .quote import _INDICATOR_DESCRIPTIONS  # noqa: F401
from .fundamentals import *  # noqa: F401,F403
from .fundamentals import _sina_stock_code, _get_financial_report_sina  # noqa: F401
from .news import *  # noqa: F401,F403
from .news import _fetch_news_eastmoney, _fetch_news_sina  # noqa: F401
from .signals import *  # noqa: F401,F403
from .signals import (  # noqa: F401
    _northbound_cache_path,
    _save_northbound_snapshot,
    _load_northbound_history,
    _BAIDU_PAE_HEADERS,
)
