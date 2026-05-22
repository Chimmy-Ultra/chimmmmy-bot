"""每日 digest 組裝：天氣 + 新聞 + 論文。"""
import asyncio
import logging

from . import economy, news, papers, weather


async def build_daily_digest() -> str:
    """並發抓所有資料，組成多段訊息（用 [SPLIT] 分隔，沿用 bot.py 的切片機制）。"""
    results = await asyncio.gather(
        weather.fetch_taipei_weather(),
        news.fetch_hn_top(10),
        papers.fetch_papers(categories=["q-fin", "econ"], days=2, max_results=15),
        economy.fetch_latest_all(),
        return_exceptions=True,
    )

    weather_text, hn_items, paper_items, econ_items = results

    sections = []

    if isinstance(weather_text, Exception):
        logging.error("digest weather 失敗: %s", weather_text)
        sections.append("🌤 台北天氣\n（抓取失敗）")
    else:
        sections.append(weather_text)

    if isinstance(hn_items, Exception):
        logging.error("digest hn 失敗: %s", hn_items)
        sections.append("📰 Hacker News\n（抓取失敗）")
    else:
        sections.append(news.format_hn(hn_items))

    if isinstance(paper_items, Exception):
        logging.error("digest papers 失敗: %s", paper_items)
        sections.append("📄 arXiv\n（抓取失敗）")
    else:
        sections.append(papers.format_papers(paper_items))

    if isinstance(econ_items, Exception):
        logging.error("digest economy 失敗: %s", econ_items)
        sections.append("📊 經濟數據\n（抓取失敗）")
    else:
        sections.append(economy.format_snapshot(econ_items))

    return "\n\n[SPLIT]\n\n".join(sections)
