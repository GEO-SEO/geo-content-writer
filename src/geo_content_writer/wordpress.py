from __future__ import annotations

import html
import os
import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlparse

import requests


class WordPressClient:
    """Lightweight WordPress REST API client using Application Passwords."""

    def __init__(
        self,
        site_url: Optional[str] = None,
        username: Optional[str] = None,
        app_password: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        timeout: int = 30,
        max_retries: int = 3,
    ) -> None:
        self.site_url = (site_url or os.environ.get("WORDPRESS_SITE_URL") or "").rstrip("/")
        self.username = username or os.environ.get("WORDPRESS_USERNAME")
        self.app_password = app_password or os.environ.get("WORDPRESS_APP_PASSWORD")
        self.client_id = client_id or os.environ.get("WORDPRESS_CLIENT_ID")
        self.client_secret = client_secret or os.environ.get("WORDPRESS_CLIENT_SECRET")
        self.timeout = timeout
        self.max_retries = max_retries

        if not self.site_url:
            raise ValueError("Missing WORDPRESS_SITE_URL. Pass site_url or set the environment variable.")
        if not self.username:
            raise ValueError("Missing WORDPRESS_USERNAME. Pass username or set the environment variable.")
        if not self.app_password:
            raise ValueError(
                "Missing WORDPRESS_APP_PASSWORD. Pass app_password or set the environment variable."
            )

    @property
    def is_wordpress_com(self) -> bool:
        host = urlparse(self.site_url).netloc.lower() or self.site_url.lower()
        return host.endswith("wordpress.com")

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = requests.request(
                    method=method,
                    url=f"{self.site_url}/wp-json/wp/v2{path}",
                    auth=(self.username, self.app_password),
                    json=json,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                return response.json()
            except requests.exceptions.RequestException as exc:
                last_error = exc
                if attempt == self.max_retries:
                    break
                time.sleep(0.8 * attempt)
        if last_error:
            raise last_error
        raise RuntimeError("WordPress request failed without an exception.")

    def _site_identifier(self) -> str:
        host = urlparse(self.site_url).netloc or self.site_url
        return quote(host, safe="")

    def _wpcom_access_token(self) -> str:
        if not self.client_id or not self.client_secret:
            raise ValueError(
                "Missing WORDPRESS_CLIENT_ID or WORDPRESS_CLIENT_SECRET. WordPress.com sites require both values."
            )
        response = requests.post(
            "https://public-api.wordpress.com/oauth2/token",
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "password",
                "username": self.username,
                "password": self.app_password,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise ValueError("WordPress.com OAuth token response did not contain an access token.")
        return token

    def create_post(
        self,
        *,
        title: str,
        content: str,
        status: str = "draft",
        slug: Optional[str] = None,
        excerpt: Optional[str] = None,
        categories: Optional[List[int]] = None,
        tags: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "title": title,
            "content": content,
            "status": status,
        }
        if slug:
            payload["slug"] = slug
        if excerpt:
            payload["excerpt"] = excerpt
        if categories:
            payload["categories"] = categories
        if tags:
            payload["tags"] = tags
        return self._request("POST", "/posts", json=payload)

    def update_post(
        self,
        post_id: int,
        *,
        title: Optional[str] = None,
        content: Optional[str] = None,
        status: Optional[str] = None,
        slug: Optional[str] = None,
        excerpt: Optional[str] = None,
        categories: Optional[List[int]] = None,
        tags: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if title is not None:
            payload["title"] = title
        if content is not None:
            payload["content"] = content
        if status is not None:
            payload["status"] = status
        if slug is not None:
            payload["slug"] = slug
        if excerpt is not None:
            payload["excerpt"] = excerpt
        if categories:
            payload["categories"] = categories
        if tags:
            payload["tags"] = tags
        return self._request("POST", f"/posts/{post_id}", json=payload)


def markdown_to_basic_html(markdown_text: str) -> str:
    """Convert markdown into WordPress-friendly HTML to avoid raw markdown leaking."""

    lines = markdown_text.splitlines()
    if lines and lines[0].strip().startswith("# "):
        lines = lines[1:]

    blocks: List[str] = []
    ul_items: List[str] = []
    ol_items: List[str] = []
    paragraph_lines: List[str] = []
    table_lines: List[str] = []
    code_lines: List[str] = []
    in_code = False

    def flush_ul() -> None:
        nonlocal ul_items
        if ul_items:
            blocks.append("<ul>" + "".join(ul_items) + "</ul>")
            ul_items = []

    def flush_ol() -> None:
        nonlocal ol_items
        if ol_items:
            blocks.append("<ol>" + "".join(ol_items) + "</ol>")
            ol_items = []

    def flush_paragraph() -> None:
        nonlocal paragraph_lines
        if paragraph_lines:
            text = " ".join(part.strip() for part in paragraph_lines if part.strip())
            blocks.append(f"<p>{_inline_markdown_to_html(text)}</p>")
            paragraph_lines = []

    def flush_table() -> None:
        nonlocal table_lines
        if table_lines:
            html_table = _table_markdown_to_html(table_lines)
            if html_table:
                blocks.append(html_table)
            table_lines = []

    def flush_code() -> None:
        nonlocal code_lines, in_code
        if code_lines:
            code_html = "\n".join(html.escape(line) for line in code_lines)
            blocks.append(f"<pre><code>{code_html}</code></pre>")
            code_lines = []
        in_code = False

    for raw_line in lines:
        line = raw_line.rstrip("\n")
        stripped = line.strip()

        if stripped.startswith("```"):
            if in_code:
                flush_code()
            else:
                flush_ul()
                flush_ol()
                flush_paragraph()
                flush_table()
                in_code = True
            continue

        if in_code:
            code_lines.append(line)
            continue

        if not stripped:
            flush_ul()
            flush_ol()
            flush_paragraph()
            flush_table()
            continue

        if stripped.startswith("|") and stripped.endswith("|"):
            flush_ul()
            flush_ol()
            flush_paragraph()
            table_lines.append(stripped)
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading_match:
            flush_ul()
            flush_ol()
            flush_paragraph()
            flush_table()
            level = len(heading_match.group(1))
            text = _inline_markdown_to_html(heading_match.group(2).strip())
            blocks.append(f"<h{level}>{text}</h{level}>")
            continue

        if re.match(r"^[-*+]\s+", stripped):
            flush_ol()
            flush_paragraph()
            flush_table()
            ul_items.append(f"<li>{_inline_markdown_to_html(stripped[2:].strip())}</li>")
            continue

        ol_match = re.match(r"^\d+\.\s+(.*)$", stripped)
        if ol_match:
            flush_ul()
            flush_paragraph()
            flush_table()
            ol_items.append(f"<li>{_inline_markdown_to_html(ol_match.group(1).strip())}</li>")
            continue

        if stripped.startswith(">"):
            flush_ul()
            flush_ol()
            flush_table()
            text = stripped.lstrip(">").strip()
            blocks.append(f"<blockquote>{_inline_markdown_to_html(text)}</blockquote>")
            continue

        flush_ul()
        flush_ol()
        flush_table()
        paragraph_lines.append(stripped)

    flush_code()
    flush_ul()
    flush_ol()
    flush_paragraph()
    flush_table()
    return "\n".join(blocks)


def _inline_markdown_to_html(text: str) -> str:
    escaped = html.escape(text, quote=False)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", escaped)
    escaped = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', escaped)
    return escaped


def _table_markdown_to_html(lines: List[str]) -> str:
    rows = []
    for line in lines:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        rows.append(cells)
    if len(rows) < 2:
        return ""
    header = rows[0]
    body = [row for row in rows[2:] if row]
    thead = "<thead><tr>" + "".join(f"<th>{_inline_markdown_to_html(cell)}</th>" for cell in header) + "</tr></thead>"
    tbody_rows = []
    for row in body:
        tbody_rows.append("<tr>" + "".join(f"<td>{_inline_markdown_to_html(cell)}</td>" for cell in row) + "</tr>")
    tbody = "<tbody>" + "".join(tbody_rows) + "</tbody>"
    return f"<table>{thead}{tbody}</table>"
