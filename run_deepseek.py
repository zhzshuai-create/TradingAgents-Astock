"""分析 A 股 — DeepSeek 版，开箱即用"""
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG
from dotenv import load_dotenv

load_dotenv()

config = DEFAULT_CONFIG.copy()
config["llm_provider"] = "deepseek"
config["deep_think_llm"] = "deepseek-chat"
config["quick_think_llm"] = "deepseek-chat"
config["output_language"] = "Chinese"
config["max_debate_rounds"] = 1
config["max_risk_discuss_rounds"] = 1

# A 股数据源
config["data_vendors"] = {
    "core_stock_apis": "a_stock",
    "technical_indicators": "a_stock",
    "fundamental_data": "a_stock",
    "news_data": "a_stock",
}

import sys

print("=" * 60)
print("TradingAgents-Astock + DeepSeek")
print("Stock: 688017 | Date: 2026-05-12")
print("=" * 60)
sys.stdout.flush()

ta = TradingAgentsGraph(debug=False, config=config)
print("Starting analysis pipeline (7 analysts → debate → risk → decision)...")
print("This may take 5-10 minutes depending on LLM response time.\n")
sys.stdout.flush()

_, decision = ta.propagate("688017", "2026-05-12")

print("\n" + "=" * 60)
print("FINAL DECISION:")
print("=" * 60)
print(decision)
