#!/usr/bin/env python3
"""
智能排班系统 - 时区工具模块

简道云 datetime 字段统一存储为 UTC 格式（如 2026-06-16T00:00:00.000Z）。
本模块提供北京时间（Asia/Shanghai, UTC+8）与 UTC 之间的转换工具。

北京时间 2026-06-16 00:00 = UTC 2026-06-15 16:00:00.000Z
简道云日期字段存储: 2026-06-16T00:00:00.000Z（UTC 零点，表示北京时间 6月16日 08:00）
"""

from datetime import datetime, timedelta, timezone

# 北京时间时区
BJT = timezone(timedelta(hours=8))


def now_bjt() -> datetime:
    """获取当前北京时间（带时区信息）"""
    return datetime.now(BJT)


def today_bjt() -> str:
    """获取今天北京时间的日期字符串 YYYY-MM-DD"""
    return now_bjt().strftime("%Y-%m-%d")


def bj_date_to_utc_midnight(date_str: str) -> str:
    """
    将北京时间日期字符串转为简道云 datetime 字段的 UTC 零点格式。

    Args:
        date_str: 北京时间日期，格式 "YYYY-MM-DD"

    Returns:
        UTC 零点格式字符串 "YYYY-MM-DDT00:00:00.000Z"

    Example:
        bj_date_to_utc_midnight("2026-06-16") -> "2026-06-16T00:00:00.000Z"
    """
    return f"{date_str}T00:00:00.000Z"


def utc_to_bj_date(utc_str: str) -> str:
    """
    将简道云 UTC datetime 字符串转为北京时间日期。

    Args:
        utc_str: UTC 时间字符串，支持 ISO 格式（含 Z 或 +00:00）

    Returns:
        北京时间日期字符串 "YYYY-MM-DD"

    Example:
        utc_to_bj_date("2026-06-15T16:00:00.000Z") -> "2026-06-16"
        utc_to_bj_date("2026-06-16T00:00:00.000Z") -> "2026-06-16"
    """
    try:
        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        bj_dt = dt.astimezone(BJT)
        return bj_dt.strftime("%Y-%m-%d")
    except Exception:
        return utc_str[:10] if len(utc_str) >= 10 else utc_str


def utc_to_bj_datetime(utc_str: str) -> datetime:
    """
    将 UTC datetime 字符串转为北京时间 datetime 对象。

    Args:
        utc_str: UTC 时间字符串

    Returns:
        北京时间 datetime 对象（带时区信息）
    """
    dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
    return dt.astimezone(BJT)


def bj_date_to_utc_range(date_str: str) -> tuple:
    """
    将北京时间单日转为 UTC 时间范围（用于简道云 datetime range 查询）。

    北京时间 6月16日 00:00 ~ 23:59 = UTC 6月15日 16:00 ~ 6月16日 15:59

    Args:
        date_str: 北京时间日期 "YYYY-MM-DD"

    Returns:
        (start_utc, end_utc) 元组，格式 "YYYY-MM-DDTHH:MM:SS.000Z"

    Example:
        bj_date_to_utc_range("2026-06-16") ->
        ("2026-06-15T16:00:00.000Z", "2026-06-16T15:59:59.000Z")
    """
    # 北京时间当天 00:00
    bj_midnight = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=BJT)
    # 转为 UTC
    utc_start = bj_midnight.astimezone(timezone.utc)
    utc_end = utc_start + timedelta(hours=23, minutes=59, seconds=59)
    return (
        utc_start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        utc_end.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
    )
