"""分析 长电科技 600584 — DeepSeek 版"""
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG
from dotenv import load_dotenv
import sys

load_dotenv()

config = DEFAULT_CONFIG.copy()
config["llm_provider"] = "deepseek"
config["deep_think_llm"] = "deepseek-chat"
config["quick_think_llm"] = "deepseek-chat"
config["output_language"] = "Chinese"
config["max_debate_rounds"] = 2
config["max_risk_discuss_rounds"] = 2
config["data_vendors"] = {
    "core_stock_apis": "a_stock",
    "technical_indicators": "a_stock",
    "fundamental_data": "a_stock",
    "news_data": "a_stock",
}

print("=" * 60)
print("TradingAgents-Astock + DeepSeek")
print("标的: 600584 长电科技 | 日期: 2026-05-13")
print("辩论轮次: 2 | 风险讨论: 2")
print("=" * 60)
sys.stdout.flush()

ta = TradingAgentsGraph(debug=False, config=config)
print("启动 7 分析师 + 多空辩论 + 风险决策 Pipeline...\n")
sys.stdout.flush()

_, decision = ta.propagate("600584", "2026-05-13")

print("\n" + "=" * 60)
print("长电科技 最终决策:")
print("=" * 60)
print(decision)
