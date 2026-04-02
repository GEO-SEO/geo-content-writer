from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional

import requests


class DagenoClient:
    """Small wrapper around the Dageno Open API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.dageno.ai/business/api",
        timeout: int = 30,
        max_retries: int = 3,
    ) -> None:
        self.api_key = api_key or os.environ.get("DAGENO_API_KEY")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries

        if not self.api_key:
            raise ValueError("Missing DAGENO_API_KEY. Pass api_key or set the environment variable.")

    @property
    def headers(self) -> Dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = requests.request(
                    method=method,
                    url=f"{self.base_url}{path}",
                    headers=self.headers,
                    params=params,
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
        raise RuntimeError("Request failed without an exception.")

    def brand_info(self) -> Dict[str, Any]:
        return self._request("GET", "/v1/open-api/brand")

    def geo_analysis(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", "/v1/open-api/geo/analysis", json=payload)

    def topics(
        self,
        start_at: str,
        end_at: str,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        return self._request(
            "GET",
            "/v1/open-api/topics",
            params={
                "startAt": start_at,
                "endAt": end_at,
                "page": page,
                "pageSize": page_size,
            },
        )

    def prompts(
        self,
        start_at: str,
        end_at: str,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        return self._request(
            "GET",
            "/v1/open-api/prompts",
            params={
                "startAt": start_at,
                "endAt": end_at,
                "page": page,
                "pageSize": page_size,
            },
        )

    def prompt_responses(
        self,
        prompt_id: str,
        start_at: str,
        end_at: str,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        return self._request(
            "GET",
            f"/v1/open-api/prompts/{prompt_id}/responses",
            params={
                "startAt": start_at,
                "endAt": end_at,
                "page": page,
                "pageSize": page_size,
            },
        )

    def prompt_response_detail(self, prompt_id: str, response_id: str) -> Dict[str, Any]:
        return self._request(
            "GET",
            f"/v1/open-api/prompts/{prompt_id}/responses/{response_id}",
        )

    def prompt_query_fanout(
        self,
        prompt_id: str,
        start_at: str,
        end_at: str,
        *,
        page: int = 1,
        page_size: int = 50,
        platforms: Optional[str] = None,
        regions: Optional[str] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "startAt": start_at,
            "endAt": end_at,
            "page": page,
            "pageSize": page_size,
        }
        if platforms:
            params["platforms"] = platforms
        if regions:
            params["regions"] = regions
        return self._request(
            "GET",
            f"/v1/open-api/prompts/{prompt_id}/query_fanout",
            params=params,
        )

    def citation_domains(
        self,
        start_at: str,
        end_at: str,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        return self._request(
            "GET",
            "/v1/open-api/citations/domains",
            params={
                "startAt": start_at,
                "endAt": end_at,
                "page": page,
                "pageSize": page_size,
            },
        )

    def citation_urls(
        self,
        start_at: str,
        end_at: str,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        return self._request(
            "GET",
            "/v1/open-api/citations/urls",
            params={
                "startAt": start_at,
                "endAt": end_at,
                "page": page,
                "pageSize": page_size,
            },
        )

    def prompt_citation_domains(
        self,
        prompt_id: str,
        start_at: str,
        end_at: str,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        return self._request(
            "GET",
            f"/v1/open-api/prompts/{prompt_id}/citations/domains",
            params={
                "startAt": start_at,
                "endAt": end_at,
                "page": page,
                "pageSize": page_size,
            },
        )

    def prompt_citation_urls(
        self,
        prompt_id: str,
        start_at: str,
        end_at: str,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        return self._request(
            "GET",
            f"/v1/open-api/prompts/{prompt_id}/citations/urls",
            params={
                "startAt": start_at,
                "endAt": end_at,
                "page": page,
                "pageSize": page_size,
            },
        )

    def content_opportunities(
        self,
        start_at: str,
        end_at: str,
        *,
        page: int = 1,
        page_size: int = 50,
        prompt_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "startAt": start_at,
            "endAt": end_at,
            "page": page,
            "pageSize": page_size,
        }
        if prompt_id:
            params["promptId"] = prompt_id
        return self._request(
            "GET",
            "/v1/open-api/opportunities/content",
            params=params,
        )

    def backlink_opportunities(
        self,
        start_at: str,
        end_at: str,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        return self._request(
            "GET",
            "/v1/open-api/opportunities/backlink",
            params={
                "startAt": start_at,
                "endAt": end_at,
                "page": page,
                "pageSize": page_size,
            },
        )

    def community_opportunities(
        self,
        start_at: str,
        end_at: str,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        return self._request(
            "GET",
            "/v1/open-api/opportunities/community",
            params={
                "startAt": start_at,
                "endAt": end_at,
                "page": page,
                "pageSize": page_size,
            },
        )

    def keyword_volume(self, keywords: list[str]) -> Dict[str, Any]:
        return self._request(
            "POST",
            "/v1/open-api/keywords/volume",
            json={"keywords": keywords},
        )
