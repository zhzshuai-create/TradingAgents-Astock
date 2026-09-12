from enum import Enum


class AnalystType(str, Enum):
    MARKET = "market"
    SOCIAL = "social"
    NEWS = "news"
    FUNDAMENTALS = "fundamentals"
    POLICY = "policy"
    HOT_MONEY = "hot_money"
    LOCKUP = "lockup"
