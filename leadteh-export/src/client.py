from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass

import requests

from .settings import Settings


LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class ApiResponse:
    content: bytes
    json_data: object
    url: str


class LeadTehClient:
    """Small read-only client. This class intentionally exposes GET only."""

    def __init__(self, settings: Settings, session: requests.Session | None = None):
        self.settings = settings
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json, text/plain, */*",
                "User-Agent": "edabalans-leadteh-export/0.1 (read-only migration)",
            }
        )
        if settings.cookie:
            self.session.headers["Cookie"] = settings.cookie
        if settings.token:
            token = settings.token
            self.session.headers["Authorization"] = (
                token if token.lower().startswith("bearer ") else f"Bearer {token}"
            )
        if settings.csrf_token:
            self.session.headers["X-CSRF-TOKEN"] = settings.csrf_token
        self.session.headers["X-Requested-With"] = "XMLHttpRequest"

    def get_tree(self) -> ApiResponse:
        return self._get(self.settings.tree_url)

    def get_scenario(self, scenario_id: int) -> ApiResponse:
        return self._get(self.settings.scenario_url, params={"scheme_id": int(scenario_id)})

    def throttle(self) -> None:
        seconds = self.settings.delay_seconds + random.uniform(
            self.settings.jitter_min, self.settings.jitter_max
        )
        time.sleep(seconds)

    def _get(self, url: str, params: dict[str, object] | None = None) -> ApiResponse:
        last_error: Exception | None = None
        for attempt in range(1, 6):
            try:
                response = self.session.get(
                    url, params=params, timeout=self.settings.timeout_seconds, allow_redirects=False
                )
                if response.status_code in (401, 403):
                    raise PermissionError(
                        f"LeadTeh returned HTTP {response.status_code}; refresh the local .env credentials"
                    )
                if 300 <= response.status_code < 400:
                    raise PermissionError(
                        f"LeadTeh redirected the API request (HTTP {response.status_code}); refresh the local session credentials"
                    )
                if response.status_code == 429 or 500 <= response.status_code < 600:
                    raise requests.HTTPError(f"retryable HTTP {response.status_code}")
                response.raise_for_status()
                try:
                    data = response.json()
                except ValueError as exc:
                    raise ValueError("LeadTeh response is not JSON (possibly a login page)") from exc
                return ApiResponse(response.content, data, response.url)
            except PermissionError:
                raise
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                if attempt == 5:
                    break
                wait = min(30.0, 2 ** (attempt - 1)) + random.uniform(0.2, 0.8)
                LOG.warning("GET failed (attempt %s/5): %s; retry in %.1fs", attempt, exc, wait)
                time.sleep(wait)
        raise RuntimeError(f"GET failed after 5 attempts: {last_error}")
