"""FRED 經濟指標：CPI、NFP、失業率、Fed Funds、GDP、PMI、零售銷售。

FRED API: https://fred.stlouisfed.org/docs/api/fred/
免費註冊 key：https://fred.stlouisfed.org/docs/api/api_key.html
"""
import asyncio
import logging
import os

import httpx

from . import state

_BASE = "https://api.stlouisfed.org/fred/series/observations"

# (series_id, 顯示名稱, 單位後綴, 是否轉「變化」)
TRACKED: list[tuple[str, str, str]] = [
    ("CPIAUCSL", "CPI (Headline)", "Index"),
    ("CPILFESL", "Core CPI", "Index"),
    ("PAYEMS", "Nonfarm Payrolls", "k jobs"),
    ("UNRATE", "失業率", "%"),
    ("FEDFUNDS", "Fed Funds Rate", "%"),
    ("GDP", "GDP", "B USD"),
    ("NAPM", "ISM 製造業 PMI", ""),
    ("RSAFS", "零售銷售", "M USD"),
]


def _api_key() -> str | None:
    key = os.environ.get("FRED_API_KEY")
    return key or None


async def _fetch_series(client: httpx.AsyncClient, series_id: str, limit: int = 2) -> list[dict]:
    key = _api_key()
    if not key:
        return []
    params = {
        "series_id": series_id,
        "api_key": key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": limit,
    }
    resp = await client.get(_BASE, params=params, timeout=20)
    resp.raise_for_status()
    return resp.json().get("observations", [])


async def fetch_latest_all() -> list[dict]:
    """抓所有追蹤指標的最新觀測值（不檢查是否新發布）。"""
    if not _api_key():
        return []
    async with httpx.AsyncClient() as client:
        tasks = [_fetch_series(client, sid) for sid, _, _ in TRACKED]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    out = []
    for (sid, name, unit), obs_list in zip(TRACKED, results):
        if isinstance(obs_list, Exception) or not obs_list:
            continue
        latest = obs_list[0]
        prev = obs_list[1] if len(obs_list) > 1 else None
        out.append({
            "series_id": sid,
            "name": name,
            "unit": unit,
            "date": latest.get("date"),
            "value": latest.get("value"),
            "prev_value": prev.get("value") if prev else None,
        })
    return out


async def check_new_releases() -> list[dict]:
    """檢查每個 series：若最新 date 比 state 記錄的 last_seen 新，視為新發布。
    回傳新發布清單；副作用：更新 last_seen。
    """
    if not _api_key():
        return []
    latest = await fetch_latest_all()
    new_releases = []
    for item in latest:
        sid = item["series_id"]
        date = item["date"]
        if not date:
            continue
        last = state.get_last_seen(sid)
        if last is None:
            # 第一次跑：只記錄，不推播（避免一啟動就發一堆舊資料）
            state.set_last_seen(sid, date)
            continue
        if date > last:
            new_releases.append(item)
            state.set_last_seen(sid, date)
    return new_releases


def _fmt_value(value: str | None, unit: str) -> str:
    if value is None or value == ".":
        return "n/a"
    try:
        v = float(value)
    except ValueError:
        return value
    return f"{v:,.2f} {unit}".rstrip()


def format_release(item: dict) -> str:
    cur = _fmt_value(item["value"], item["unit"])
    prev = _fmt_value(item["prev_value"], item["unit"])
    change = ""
    try:
        if item["value"] and item["prev_value"]:
            diff = float(item["value"]) - float(item["prev_value"])
            arrow = "📈" if diff > 0 else ("📉" if diff < 0 else "➡️")
            change = f" {arrow} {diff:+.2f}"
    except (TypeError, ValueError):
        pass
    return f"• *{item['name']}* ({item['date']}): {cur}{change}\n   前值：{prev}"


def format_releases_batch(items: list[dict], header: str = "📊 *經濟數據更新*") -> str:
    if not items:
        return ""
    return header + "\n" + "\n".join(format_release(it) for it in items)


def format_snapshot(items: list[dict]) -> str:
    if not items:
        if not _api_key():
            return "📊 經濟數據\n（未設定 FRED_API_KEY，跳過）"
        return "📊 經濟數據\n（抓不到資料）"
    return "📊 *經濟數據快照*\n" + "\n".join(format_release(it) for it in items)
