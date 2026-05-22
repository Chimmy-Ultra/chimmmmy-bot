"""arXiv q-fin + econ + 關鍵字過濾，免 API key。

用 stdlib xml.etree 解析 Atom feed，不依賴 feedparser。
"""
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET

import httpx

_BASE = "http://export.arxiv.org/api/query"
_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}


async def fetch_papers(
    categories: list[str] | None = None,
    keywords: list[str] | None = None,
    days: int = 2,
    max_results: int = 15,
) -> list[dict]:
    categories = categories or ["q-fin", "econ"]
    cat_query = " OR ".join(f"cat:{c}.*" for c in categories)

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    date_q = f"submittedDate:[{start:%Y%m%d%H%M} TO {end:%Y%m%d%H%M}]"

    params = {
        "search_query": f"({cat_query}) AND {date_q}",
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": max_results,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(_BASE, params=params)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)

    out = []
    kw_lower = [k.lower() for k in (keywords or [])]
    for entry in root.findall("atom:entry", _NS):
        title = (entry.findtext("atom:title", "", _NS) or "").replace("\n", " ").strip()
        summary = (entry.findtext("atom:summary", "", _NS) or "").replace("\n", " ").strip()
        if kw_lower:
            blob = (title + " " + summary).lower()
            if not any(k in blob for k in kw_lower):
                continue
        link = ""
        for ln in entry.findall("atom:link", _NS):
            if ln.attrib.get("rel") == "alternate" or ln.attrib.get("type") == "text/html":
                link = ln.attrib.get("href", "")
                break
        if not link:
            link = entry.findtext("atom:id", "", _NS) or ""
        authors = [
            (a.findtext("atom:name", "", _NS) or "").strip()
            for a in entry.findall("atom:author", _NS)
        ]
        published = (entry.findtext("atom:published", "", _NS) or "")[:10]
        out.append({
            "title": title,
            "url": link,
            "authors": ", ".join(authors[:3]),
            "published": published,
            "summary": summary,
        })
    return out


def format_papers(items: list[dict], header: str = "📄 *arXiv 新論文 (q-fin + econ)*") -> str:
    if not items:
        return f"{header}\n（過去兩天沒有匹配的論文）"
    lines = [header]
    for i, p in enumerate(items[:10], 1):
        lines.append(f"{i}. [{p['title']}]({p['url']})\n   _{p['authors']} · {p['published']}_")
    return "\n".join(lines)
