"""Read-only connectors to accounting systems (Phase E6).

An adapter turns one provider's API into canonical dataset rows. Adapters only read:
OAuth scopes are read scopes and no adapter has a write method. Every HTTP call goes
through ``Http``, which spaces requests per sync (rate limit), retries 429 and 5xx
responses with capped exponential backoff, and turns failures into safe messages.

Register a new provider (QuickBooks, Xero, Dynamics 365, NetSuite, SAP) by adding an
adapter module and an entry in ``ADAPTERS``; the service, API and UI need no change.
Field mappings follow the providers' public documentation and are unverified against
live accounts until someone checks them (``MAPPING_STATUS``).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from app.config import get_settings
from app.models import ConnectorProvider, DatasetKind

MAPPING_STATUS = "unverified"


class ConnectorError(Exception):
    """A failure whose message is safe to show (no tokens, URLs with secrets or payloads)."""


class ConnectorAuthError(ConnectorError):
    pass


@dataclass
class FetchResult:
    columns: list[str]
    rows: list[dict[str, Any]] = field(default_factory=list)


class Adapter(Protocol):
    provider: ConnectorProvider
    label: str
    auth: str  # "oauth" or "api_key"
    kinds: tuple[DatasetKind, ...]
    scopes: tuple[str, ...]

    def configured(self) -> bool: ...

    def authorize_url(self, state: str, challenge: str, redirect_uri: str) -> str: ...

    def exchange(self, http: Http, code: str, verifier: str, redirect_uri: str) -> dict[str, Any]:
        """Code → secret (tokens). OAuth adapters only."""
        ...

    def refresh(self, http: Http, secret: dict[str, Any]) -> dict[str, Any]: ...

    def connect(self, http: Http, secret: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        """Check the credentials work; returns config to store (e.g. organisation id)."""
        ...

    def fetch(
        self,
        http: Http,
        kind: DatasetKind,
        secret: dict[str, Any],
        config: dict[str, Any],
        since: Any = None,
    ) -> FetchResult: ...


# Tests replace this with an httpx.MockTransport; production uses the default transport.
transport_factory: Callable[[], httpx.BaseTransport | None] = lambda: None  # noqa: E731


class Http:
    """Rate-limited, retrying HTTP client for one sync or one authorisation."""

    def __init__(
        self,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        s = get_settings()
        self.client = httpx.Client(
            transport=transport_factory(),
            timeout=s.connector_timeout_seconds,
            follow_redirects=False,
        )
        self.min_interval = s.connector_min_interval_ms / 1000
        self.max_retries = s.connector_max_retries
        self.sleep = sleep
        self.clock = clock
        self._last: float | None = None
        self.requests = 0

    def __enter__(self) -> Http:
        return self

    def __exit__(self, *_: object) -> None:
        self.client.close()

    def _space(self) -> None:
        if self._last is not None:
            wait = self.min_interval - (self.clock() - self._last)
            if wait > 0:
                self.sleep(wait)
        self._last = self.clock()

    def request(self, method: str, url: str, **kw: Any) -> httpx.Response:
        for attempt in range(self.max_retries + 1):
            self._space()
            self.requests += 1
            try:
                r = self.client.request(method, url, **kw)
            except httpx.HTTPError as exc:
                if attempt == self.max_retries:
                    raise ConnectorError(
                        f"The provider could not be reached ({type(exc).__name__})."
                    ) from exc
                self.sleep(min(2**attempt, 30))
                continue
            if r.status_code in (401, 403):
                raise ConnectorAuthError("The provider refused the credentials.")
            if r.status_code == 429 or r.status_code >= 500:
                if attempt == self.max_retries:
                    raise ConnectorError(f"The provider kept failing (HTTP {r.status_code}).")
                self.sleep(_retry_after(r, attempt))
                continue
            if r.status_code >= 400:
                raise ConnectorError(f"The provider rejected the request (HTTP {r.status_code}).")
            return r
        raise ConnectorError("The provider kept failing.")  # pragma: no cover

    def json(self, method: str, url: str, **kw: Any) -> Any:
        r = self.request(method, url, **kw)
        try:
            return r.json()
        except ValueError as exc:
            raise ConnectorError("The provider returned something other than JSON.") from exc


def _retry_after(r: httpx.Response, attempt: int) -> float:
    raw = r.headers.get("retry-after", "")
    if raw.isdigit():
        return float(min(int(raw), 60))
    return float(min(2**attempt, 30))


def adapters() -> dict[ConnectorProvider, Adapter]:
    from app.connectors.odoo import OdooAdapter
    from app.connectors.zoho import ZohoBooksAdapter

    return {
        ConnectorProvider.ZOHO_BOOKS: ZohoBooksAdapter(),
        ConnectorProvider.ODOO: OdooAdapter(),
    }


def adapter(provider: ConnectorProvider) -> Adapter:
    return adapters()[provider]
