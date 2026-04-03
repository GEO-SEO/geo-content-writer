from __future__ import annotations

import re
from typing import Any, Dict, List
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


def crawl_citation_pages(urls: List[str], *, limit: int = 5, timeout: int = 20, max_candidates: int = 60) -> List[Dict[str, Any]]:
    pages: List[Dict[str, Any]] = []
    article_count = 0
    for url in urls[:max_candidates]:
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
            if pages[-1]["is_article_like"]:
                article_count += 1
                if article_count >= limit:
                    break
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
                    "is_article_like": False,
                    "page_kind": "error",
                }
            )
    return pages


def analyze_citation_patterns(pages: List[Dict[str, Any]]) -> Dict[str, Any]:
    article_pages = [page for page in pages if page.get("status") == "ok" and page.get("is_article_like")]
    support_pages = [page for page in pages if page.get("status") == "ok" and not page.get("is_article_like")]
    if not article_pages:
        return {
            "page_count": 0,
            "article_page_count": 0,
            "support_page_count": len(support_pages),
            "learning_mode": "fallback_support_only",
            "dominant_title_pattern": "unknown",
            "common_heading_patterns": [],
            "table_presence_rate": 0.0,
            "list_presence_rate": 0.0,
            "faq_presence_rate": 0.0,
            "recommended_article_type": "explainer",
        }

    title_patterns: List[str] = []
    heading_terms: Dict[str, int] = {}
    intent_terms: Dict[str, int] = {}
    table_count = 0
    list_count = 0
    faq_count = 0

    for page in article_pages:
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
        for intent in _page_intents(page):
            intent_terms[intent] = intent_terms.get(intent, 0) + 1

        table_count += 1 if page.get("has_table") else 0
        list_count += 1 if page.get("has_list") else 0
        faq_count += 1 if page.get("has_faq_signal") else 0

    recommended_article_type = max(set(title_patterns), key=title_patterns.count)
    common_headings = sorted(heading_terms.items(), key=lambda item: item[1], reverse=True)[:8]
    common_intents = sorted(intent_terms.items(), key=lambda item: item[1], reverse=True)[:8]

    learning_mode = "article_first" if len(article_pages) >= 3 else "article_first_fallback"

    return {
        "page_count": len(article_pages),
        "article_page_count": len(article_pages),
        "support_page_count": len(support_pages),
        "learning_mode": learning_mode,
        "dominant_title_pattern": recommended_article_type,
        "common_heading_patterns": [heading for heading, _ in common_headings],
        "common_intents": [intent for intent, _ in common_intents],
        "table_presence_rate": round(table_count / len(article_pages), 2),
        "list_presence_rate": round(list_count / len(article_pages), 2),
        "faq_presence_rate": round(faq_count / len(article_pages), 2),
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
    page_kind = _classify_page_kind(title, h1, headings, urlparse((soup.find("meta", property="og:url") or {}).get("content", "") if soup.find("meta", property="og:url") else "").netloc)
    is_article_like = _is_article_like(title, h1, headings, paragraphs)

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
        "page_kind": page_kind,
        "is_article_like": is_article_like,
    }


def _normalize_heading(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9\s]", " ", text.lower())
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned


def _page_intents(page: Dict[str, Any]) -> List[str]:
    haystack = " ".join(
        [
            page.get("title", ""),
            page.get("meta_description", ""),
            page.get("h1", ""),
            " ".join(page.get("headings", [])[:12]),
            page.get("paragraph_preview", ""),
        ]
    ).lower()
    intents: List[str] = []
    checks = {
        "find_best_option": ["best", "top", "must-have", "top picks"],
        "compare_options": ["vs", "compare", "comparison", "which one"],
        "choose_criteria": ["what to look for", "how to choose", "criteria", "factors"],
        "price_value": ["price", "cheap", "discount", "deal", "value"],
        "trust_support": ["reviews", "support", "ratings", "reliable", "trust"],
        "workflow_convenience": ["all in one", "one place", "plan", "itinerary", "book"],
    }
    for label, keywords in checks.items():
        if any(keyword in haystack for keyword in keywords):
            intents.append(label)
    return intents or ["general_information"]


def _classify_page_kind(title: str, h1: str, headings: List[str], domain: str) -> str:
    haystack = " ".join([title, h1] + headings).lower()
    if any(token in haystack for token in ["apps on google play", "app store", "about this app", "ratings and reviews"]):
        return "app_listing"
    if any(token in haystack for token in ["reddit", "community", "forum", "comments"]):
        return "forum"
    if any(token in haystack for token in ["best", "top", "guide", "how to", "comparison", "vs"]):
        return "article"
    return "unknown"


def _is_article_like(title: str, h1: str, headings: List[str], paragraphs: List[str]) -> bool:
    if not title or not h1:
        return False
    if len(paragraphs) < 4:
        return False
    if len(" ".join(paragraphs[:8]).split()) < 350:
        return False
    heading_count = len([heading for heading in headings if heading.strip()])
    if heading_count < 3:
        return False
    haystack = " ".join([title, h1] + headings).lower()
    if any(token in haystack for token in ["apps on google play", "app store", "ratings and reviews", "similar apps"]):
        return False
    if any(token in haystack for token in ["reddit", "community", "comments", "leave a reply"]):
        return False
    return True
