from __future__ import annotations

import html
import os
import re
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
    ) -> None:
        self.site_url = (site_url or os.environ.get("WORDPRESS_SITE_URL") or "").rstrip("/")
        self.username = username or os.environ.get("WORDPRESS_USERNAME")
        self.app_password = app_password or os.environ.get("WORDPRESS_APP_PASSWORD")
        self.client_id = client_id or os.environ.get("WORDPRESS_CLIENT_ID")
        self.client_secret = client_secret or os.environ.get("WORDPRESS_CLIENT_SECRET")
        self.timeout = timeout

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
        if self.is_wordpress_com:
            response = requests.request(
                method=method,
                url=f"https://public-api.wordpress.com/wp/v2/sites/{self._site_identifier()}{path}",
                headers={
                    "Authorization": f"Bearer {self._wpcom_access_token()}",
                    "Content-Type": "application/json",
                },
                json=json,
                timeout=self.timeout,
            )
        else:
            response = requests.request(
                method=method,
                url=f"{self.site_url}/wp-json/wp/v2{path}",
                auth=(self.username, self.app_password),
                json=json,
                timeout=self.timeout,
            )
        response.raise_for_status()
        return response.json()

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


def markdown_to_basic_html(markdown_text: str) -> str:
    """Convert simple markdown-like draft output into WordPress-friendly HTML."""

    lines = markdown_text.splitlines()
    blocks: List[str] = []
    list_items: List[str] = []
    paragraph_lines: List[str] = []

    def flush_list() -> None:
        nonlocal list_items
        if list_items:
            blocks.append("<ul>" + "".join(list_items) + "</ul>")
            list_items = []

    def flush_paragraph() -> None:
        nonlocal paragraph_lines
        if paragraph_lines:
            text = " ".join(part.strip() for part in paragraph_lines if part.strip())
            blocks.append(f"<p>{_inline_markdown_to_html(text)}</p>")
            paragraph_lines = []

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            flush_list()
            flush_paragraph()
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading_match:
            flush_list()
            flush_paragraph()
            level = len(heading_match.group(1))
            text = _inline_markdown_to_html(heading_match.group(2).strip())
            blocks.append(f"<h{level}>{text}</h{level}>")
            continue

        if stripped.startswith("- "):
            flush_paragraph()
            item_text = _inline_markdown_to_html(stripped[2:].strip())
            list_items.append(f"<li>{item_text}</li>")
            continue

        flush_list()
        paragraph_lines.append(stripped)

    flush_list()
    flush_paragraph()
    return "\n".join(blocks)


def _inline_markdown_to_html(text: str) -> str:
    escaped = html.escape(text, quote=False)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", escaped)
    return escaped
