"""Hacker News Top Stories，免 API key。"""
import asyncio
import httpx

_BASE = "https://hacker-news.firebaseio.com/v0"


async def _fetch_item(client: httpx.AsyncClient, item_id: int) -> dict | None:
    try:
        resp = await client.get(f"{_BASE}/item/{item_id}.json", timeout=10)
        resp.raise_for_status()
        return resp.json()
    except (httpx.HTTPError, ValueError):
        return None


async def fetch_hn_top(n: int = 10) -> list[dict]:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{_BASE}/topstories.json")
        resp.raise_for_status()
        ids = resp.json()[:n]
        items = await asyncio.gather(*[_fetch_item(client, i) for i in ids])

    out = []
    for item in items:
        if not item or item.get("type") != "story":
            continue
        out.append({
            "title": item.get("title", ""),
            "url": item.get("url") or f"https://news.ycombinator.com/item?id={item['id']}",
            "score": item.get("score", 0),
            "comments": item.get("descendants", 0),
        })
    return out


def format_hn(items: list[dict]) -> str:
    if not items:
        return "📰 *Hacker News*\n（沒抓到資料）"
    lines = ["📰 *Hacker News Top*"]
    for i, it in enumerate(items, 1):
        lines.append(f"{i}. [{it['title']}]({it['url']}) — {it['score']}↑ / {it['comments']}💬")
    return "\n".join(lines)
