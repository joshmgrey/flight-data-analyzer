"""Minimal OpenSky Network REST client for `/states/all` (ICD section 2)."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import requests

from fda.config import BoundingBox

log = logging.getLogger(__name__)

STATES_URL = "https://opensky-network.org/api/states/all"
TOKEN_URL = (
    "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
)
USER_AGENT = "flight-data-analyzer/0.1 (non-commercial portfolio project)"


class OpenSkyError(Exception):
    def __init__(self, message: str, http_status: int | None = None) -> None:
        super().__init__(message)
        self.http_status = http_status


class RateLimited(OpenSkyError):
    """HTTP 429: the daily credit budget is exhausted (REQ-003)."""

    def __init__(self, retry_after_s: int | None) -> None:
        super().__init__(f"rate limited, retry after {retry_after_s} s", http_status=429)
        self.retry_after_s = retry_after_s


class UpstreamError(OpenSkyError):
    """Network failure or a non-429 HTTP error that survived retries (REQ-004)."""


class SchemaError(OpenSkyError):
    """The response body does not match the documented format."""


@dataclass(frozen=True)
class StatesResponse:
    api_time: int
    rows: list[Any]
    http_status: int
    credits_remaining: int | None


def _header_int(headers: Any, name: str) -> int | None:
    try:
        return int(headers.get(name))
    except (TypeError, ValueError):
        return None


class OpenSkyClient:
    def __init__(
        self,
        session: requests.Session | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        max_retries: int = 2,
        backoff_s: float = 2.0,
        timeout_s: float = 20.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.session = session or requests.Session()
        self.client_id = client_id
        self.client_secret = client_secret
        self.max_retries = max_retries
        self.backoff_s = backoff_s
        self.timeout_s = timeout_s
        self._sleep = sleep
        self._clock = clock
        self._token: str | None = None
        self._token_expires_at = 0.0

    @property
    def authenticated(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def _bearer_token(self) -> str:
        """OAuth2 client-credentials token, cached until 30 s before expiry (REQ-005)."""
        if self._token and self._clock() < self._token_expires_at - 30:
            return self._token
        try:
            resp = self.session.post(
                TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                timeout=self.timeout_s,
            )
        except requests.RequestException as exc:
            raise UpstreamError(f"token request failed: {exc}") from exc
        if resp.status_code != 200:
            raise UpstreamError(f"token request returned {resp.status_code}", resp.status_code)
        body = resp.json()
        self._token = body["access_token"]
        self._token_expires_at = self._clock() + float(body.get("expires_in", 300))
        return self._token

    def fetch_states(self, bbox: BoundingBox) -> StatesResponse:
        headers = {"User-Agent": USER_AGENT}
        if self.authenticated:
            headers["Authorization"] = f"Bearer {self._bearer_token()}"
        params = {**bbox.as_params(), "extended": 1}

        last_error: OpenSkyError | None = None
        for attempt in range(self.max_retries + 1):
            if attempt:
                delay = self.backoff_s * 2 ** (attempt - 1)
                log.warning("retrying OpenSky request attempt=%d delay_s=%.1f", attempt, delay)
                self._sleep(delay)
            try:
                resp = self.session.get(
                    STATES_URL, params=params, headers=headers, timeout=self.timeout_s
                )
            except requests.RequestException as exc:
                last_error = UpstreamError(f"network error: {exc}")
                continue

            if resp.status_code == 429:
                # Retrying would only burn the rest of the budget; wait for the next poll.
                raise RateLimited(
                    _header_int(resp.headers, "X-Rate-Limit-Retry-After-Seconds")
                )
            if resp.status_code >= 500:
                last_error = UpstreamError(f"HTTP {resp.status_code}", resp.status_code)
                continue
            if resp.status_code != 200:
                raise UpstreamError(f"HTTP {resp.status_code}", resp.status_code)
            return self._parse(resp)

        assert last_error is not None
        raise last_error

    @staticmethod
    def _parse(resp: requests.Response) -> StatesResponse:
        try:
            body = resp.json()
        except ValueError as exc:
            raise SchemaError("response is not JSON", resp.status_code) from exc
        if not isinstance(body, dict) or not isinstance(body.get("time"), int):
            raise SchemaError("response lacks integer 'time'", resp.status_code)
        rows = body.get("states")
        if rows is None:
            rows = []  # OpenSky returns null when nothing is in the box
        if not isinstance(rows, list):
            raise SchemaError("'states' is not an array", resp.status_code)
        return StatesResponse(
            api_time=body["time"],
            rows=rows,
            http_status=resp.status_code,
            credits_remaining=_header_int(resp.headers, "X-Rate-Limit-Remaining"),
        )
