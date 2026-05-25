#!/usr/bin/env python3
"""Claude Code 週用量配速表。

週用量額度每週五 15:00 重置；把額度平均攤到整週算出「均速」，
讓你對照自己用得偏快還偏慢。純 stdlib，無外部依賴。

時區用環境變數 PACE_TZ 設定（預設 Asia/Taipei）；抓不到 tzdata 時
fallback 到固定 UTC+8。
"""
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

RESET_WEEKDAY = 4   # 週一=0 ... 週五=4
RESET_HOUR = 15     # 下午三點
WEEK_HOURS = 7 * 24  # 168


def resolve_tz():
    name = os.environ.get("PACE_TZ", "Asia/Taipei")
    try:
        return ZoneInfo(name)
    except Exception:
        return timezone(timedelta(hours=8))


def week_window(now):
    """回傳 (上次重置, 下次重置)，皆為週五 15:00。"""
    days_since = (now.weekday() - RESET_WEEKDAY) % 7
    last_reset = now.replace(hour=RESET_HOUR, minute=0, second=0, microsecond=0) \
                    - timedelta(days=days_since)
    if last_reset > now:
        last_reset -= timedelta(days=7)
    return last_reset, last_reset + timedelta(days=7)


def build_pace_table(now=None):
    tz = resolve_tz()
    now = now or datetime.now(tz)
    last_reset, next_reset = week_window(now)

    elapsed_h = (now - last_reset).total_seconds() / 3600
    progress = elapsed_h / WEEK_HOURS
    per_hour = 100 / WEEK_HOURS
    per_day = per_hour * 24
    on_pace = progress * 100
    remaining_h = WEEK_HOURS - elapsed_h

    weekdays = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]
    lines = []
    for d in range(8):
        cp = last_reset + timedelta(days=d)
        pct = min(d * per_day, 100)
        mark = "  ← 現在" if cp <= now < cp + timedelta(days=1) else ""
        lines.append(f"{weekdays[cp.weekday()]} {cp:%m/%d %H:%M} → {pct:5.1f}%{mark}")
    table = "\n".join(lines)

    return (
        "📊 Claude Code 用量配速表\n"
        "週期：每週五 15:00 重置\n\n"
        "⏱ 本週進度\n"
        f"上次重置：{last_reset:%m/%d %H:%M}\n"
        f"下次重置：{next_reset:%m/%d %H:%M}\n"
        f"已過 {elapsed_h:.1f} 小時 / {WEEK_HOURS}（{progress * 100:.1f}%）\n"
        f"剩餘 {remaining_h:.1f} 小時\n\n"
        "🎯 均速配速（把額度平均攤到整週）\n"
        f"每小時：{per_hour:.2f}%\n"
        f"每天：{per_day:.1f}%\n"
        f"此刻應在：{on_pace:.1f}%（用超過代表偏快，用不到代表偏慢）\n\n"
        f"📅 每日檢查點\n{table}"
    )


if __name__ == "__main__":
    print(build_pace_table())
