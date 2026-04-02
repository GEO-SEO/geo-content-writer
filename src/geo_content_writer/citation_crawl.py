from __future__ import annotations

import re
from typing import Any, Dict, List

import requests
from bs4 import BeautifulSoup


def crawl_citation_pages(urls: List[str], *, limit: int = 5, timeout: int = 20) -> List[Dict[str, Any]]:
    pages: List[Dict[str, Any]] = []
    for url in urls[:limit]:
        try:
            response = requests.get(
                url,
                timeout=timeout,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; GEOContentWriter/1.0; +https://github.com/GEO-SEO/geo-content-writer)"
                },
            )
            response.raise_for_status()
            html = response.text
            pages.append(
                {
                    "url": url,
                    "status": "ok",
                    **_extract_page_features(html),
                }
            )
        except Exception as exc:
            pages.append(
                {
                    "url": url,
                    "status": "error",
                    "error": str(exc),
                    "title": "",
                    "meta_description": "",
                    "h1": "",
                    "headings": [],
                    "paragraph_preview": "",
                    "has_table": False,
                    "has_list": False,
                    "has_faq_signal": False,
                    "word_count": 0,
                }
            )
    return pages


def analyze_citation_patterns(pages: List[Dict[str, Any]]) -> Dict[str, Any]:
    ok_pages = [page for page in pages if page.get("status") == "ok"]
    if not ok_pages:
        return {
            "page_count": 0,
            "dominant_title_pattern": "unknown",
            "common_heading_patterns": [],
            "table_presence_rate": 0.0,
            "list_presence_rate": 0.0,
            "faq_presence_rate": 0.0,
            "recommended_article_type": "explainer",
        }

    title_patterns: List[str] = []
    heading_terms: Dict[str, int] = {}
    table_count = 0
    list_count = 0
    faq_count = 0

    for page in ok_pages:
        title = (page.get("title") or "").lower()
        if any(token in title for token in ["best", "top"]):
            title_patterns.append("recommendation")
        elif any(token in title for token in ["vs", "compare", "comparison"]):
            title_patterns.append("comparison")
        elif any(token in title for token in ["how to", "guide"]):
            title_patterns.append("guide")
        else:
            title_patterns.append("explainer")

        for heading in page.get("headings", [])[:10]:
            normalized = _normalize_heading(heading)
            if normalized:
                heading_terms[normalized] = heading_terms.get(normalized, 0) + 1

        table_count += 1 if page.get("has_table") else 0
        list_count += 1 if page.get("has_list") else 0
        faq_count += 1 if page.get("has_faq_signal") else 0

    recommended_article_type = max(set(title_patterns), key=title_patterns.count)
    common_headings = sorted(heading_terms.items(), key=lambda item: item[1], reverse=True)[:8]

    return {
        "page_count": len(ok_pages),
        "dominant_title_pattern": recommended_article_type,
        "common_heading_patterns": [heading for heading, _ in common_headings],
        "table_presence_rate": round(table_count / len(ok_pages), 2),
        "list_presence_rate": round(list_count / len(ok_pages), 2),
        "faq_presence_rate": round(faq_count / len(ok_pages), 2),
        "recommended_article_type": recommended_article_type,
    }


def _extract_page_features(html: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    meta_description = ""
    meta = soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        meta_description = meta["content"].strip()

    h1 = soup.find("h1").get_text(" ", strip=True) if soup.find("h1") else ""
    headings = [node.get_text(" ", strip=True) for node in soup.find_all(["h2", "h3"]) if node.get_text(" ", strip=True)]
    paragraphs = [node.get_text(" ", strip=True) for node in soup.find_all("p") if node.get_text(" ", strip=True)]
    paragraph_preview = " ".join(paragraphs[:3])[:900]
    text = soup.get_text(" ", strip=True)

    return {
        "title": title,
        "meta_description": meta_description,
        "h1": h1,
        "headings": headings,
        "paragraph_preview": paragraph_preview,
        "has_table": bool(soup.find("table")),
        "has_list": bool(soup.find(["ul", "ol"])),
        "has_faq_signal": any("faq" in heading.lower() or "questions" in heading.lower() for heading in headings),
        "word_count": len(text.split()),
    }


def _normalize_heading(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9\s]", " ", text.lower())
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned
