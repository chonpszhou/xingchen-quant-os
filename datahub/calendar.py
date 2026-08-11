"""多市场交易日历（v1：股票类按工作日，加密 7x24；节假日日历后续接入）"""

from __future__ import annotations

import datetime as dt

import pandas as pd

MARKETS = ("A股", "港股", "美股", "虚拟货币", "期权")
CRYPTO = "虚拟货币"


def equity_days(start, end):
    """A股/港股/美股默认交易日：周一至周五（节假日未细分，后续接入交易日历表）"""
    return pd.bdate_range(start=start, end=end)


def is_trading_day(market, day=None):
    day = day or dt.date.today()
    if market == CRYPTO:
        return True
    return day.weekday() < 5


def trading_days(market, start, end):
    if market == CRYPTO:
        return pd.date_range(start=start, end=end)
    return equity_days(start, end)
