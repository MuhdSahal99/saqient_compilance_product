"""Phase E6: read-only connectors. Every provider call goes to an httpx.MockTransport;
no live account is contacted. Provider payloads below are synthetic."""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlalchemy.orm import Session

from app import connectors as conn
from app.config import ConfigError, Settings, get_settings
from app.models import Connector, Role
from tests.conftest import Tenant, login
from tests.test_datasets import make_entity

ACCESS = "synthetic-access-token-1"
REFRESH = "synthetic-refresh-token-1"
API_KEY = "synthetic-odoo-api-key"


class FakeZoho:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.token_forms: list[dict[str, list[str]]] = []
        self.invoices = [
            {
                "invoice_number": "INV-1",
                "date": "2026-01-05",
                "customer_name": "Synthetic A",
                "sub_total": 100,
                "tax_total": 5,
                "total": 105,
                "currency_code": "AED",
            },
            {
                "invoice_number": "INV-2",
                "date": "2026-01-06",
                "customer_name": "Synthetic B",
                "sub_total": 200,
                "tax_total": 10,
                "total": 210,
                "currency_code": "AED",
            },
            {
                "invoice_number": "INV-3",
                "date": "2026-01-07",
                "customer_name": "Synthetic C",
                "sub_total": 300,
                "tax_total": 15,
                "total": 315,
                "currency_code": "AED",
            },
        ]
        self.throttle_once = True
        self.refuse = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append((request.method, path))
        if path == "/oauth/v2/token":
            form = parse_qs(request.content.decode())
            self.token_forms.append(form)
            # Short-lived, so the first sync refreshes it.
            return httpx.Response(
                200,
                json={"access_token": ACCESS, "refresh_token": REFRESH, "expires_in": 60},
            )
        assert request.headers["authorization"] == f"Zoho-oauthtoken {ACCESS}"
        if self.refuse:
            return httpx.Response(401, json={"code": 57})
        if path.endswith("/organizations"):
            return httpx.Response(
                200, json={"code": 0, "organizations": [{"organization_id": "999", "name": "Syn"}]}
            )
        if path.endswith("/invoices"):
            assert request.url.params["organization_id"] == "999"
            if self.throttle_once:
                self.throttle_once = False
                return httpx.Response(429, headers={"retry-after": "0"})
            page = int(request.url.params["page"])
            items = self.invoices[:2] if page == 1 else self.invoices[2:]
            return httpx.Response(
                200,
                json={"code": 0, "invoices": items, "page_context": {"has_more_page": page == 1}},
            )
        return httpx.Response(404)


@pytest.fixture
def enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "connectors_enabled", True)
    monkeypatch.setattr(s, "zoho_client_id", "synthetic-client")
    monkeypatch.setattr(s, "zoho_client_secret", "synthetic-secret")
    monkeypatch.setattr(s, "connector_min_interval_ms", 0)


def _mock(monkeypatch: pytest.MonkeyPatch, handler: Any) -> None:
    monkeypatch.setattr(conn, "transport_factory", lambda: httpx.MockTransport(handler))


def test_off_by_default(tenant_a: Tenant, db: Session) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    entity = make_entity(db, tenant_a)
    st = admin.get("/api/connectors/status").json()
    assert st["enabled"] is False
    assert {p["provider"] for p in st["providers"]} == {"zoho_books", "odoo"}
    assert all(p["mapping_status"] == "unverified" for p in st["providers"])
    body = {"entity_id": str(entity.id), "provider": "zoho_books", "name": "Syn Zoho"}
    assert admin.post("/api/connectors", json=body).status_code == 409


def test_zoho_oauth_and_sync(
    tenant_a: Tenant, tenant_b: Tenant, db: Session, enabled: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeZoho()
    _mock(monkeypatch, fake)
    c = {r: login(tenant_a.users[r]) for r in (Role.ORG_ADMIN, Role.ANALYST, Role.VIEWER)}
    admin, analyst, viewer = c[Role.ORG_ADMIN], c[Role.ANALYST], c[Role.VIEWER]
    other = login(tenant_b.users[Role.ORG_ADMIN])
    entity = make_entity(db, tenant_a)
    body = {"entity_id": str(entity.id), "provider": "zoho_books", "name": "Syn Zoho"}
    assert analyst.post("/api/connectors", json=body).status_code == 403
    assert other.post("/api/connectors", json=body).status_code == 404  # foreign entity
    bad = {**body, "api_key": "x" * 10}
    assert admin.post("/api/connectors", json=bad).status_code == 422
    r = admin.post("/api/connectors", json=body)
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    assert r.json()["status"] == "pending" and r.json()["has_credentials"] is False
    assert all(s.endswith(".READ") for s in r.json()["scopes"])
    assert other.get(f"/api/connectors/{cid}").status_code == 404
    assert other.post(f"/api/connectors/{cid}/authorize").status_code == 404
    assert analyst.post(f"/api/connectors/{cid}/authorize").status_code == 403

    url = admin.post(f"/api/connectors/{cid}/authorize").json()["url"]
    q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    assert url.startswith("https://accounts.zoho.com/oauth/v2/auth?")
    assert q["code_challenge_method"] == "S256" and q["access_type"] == "offline"
    assert q["redirect_uri"].endswith("/api/connectors/oauth/callback")
    cb = "/api/connectors/oauth/callback"
    assert admin.get(cb, params={"state": "wrong-state-123", "code": "c"}).status_code == 404
    assert other.get(cb, params={"state": q["state"], "code": "c"}).status_code == 404
    done = admin.get(cb, params={"state": q["state"], "code": "auth-code"}, follow_redirects=False)
    assert done.status_code == 303 and done.headers["location"].endswith(
        f"/connectors?connector={cid}&result=connected"
    )
    form = fake.token_forms[0]
    assert form["grant_type"] == ["authorization_code"] and form["code"] == ["auth-code"]
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"][0].encode()).digest())
        .decode()
        .rstrip("=")
    )
    assert challenge == q["code_challenge"]
    # The state is single-use.
    assert admin.get(cb, params={"state": q["state"], "code": "again"}).status_code == 404

    got = viewer.get(f"/api/connectors/{cid}")
    assert got.status_code == 200 and got.json()["status"] == "connected"
    assert got.json()["config"]["organization_id"] == "999"
    assert ACCESS not in got.text and REFRESH not in got.text
    row = db.get(Connector, cid)
    db.refresh(row)
    assert row is not None and row.secret_enc and ACCESS not in row.secret_enc

    assert (
        viewer.post(f"/api/connectors/{cid}/sync", json={"kind": "sales_register"}).status_code
        == 403
    )
    assert (
        other.post(f"/api/connectors/{cid}/sync", json={"kind": "sales_register"}).status_code
        == 404
    )
    assert (
        analyst.post(f"/api/connectors/{cid}/sync", json={"kind": "trial_balance"}).status_code
        == 422
    )
    s1 = analyst.post(f"/api/connectors/{cid}/sync", json={"kind": "sales_register"})
    assert s1.status_code == 202, s1.text
    s1j = s1.json()
    assert s1j["status"] == "succeeded" and s1j["rows"] == 3, s1j
    assert s1j["dataset_version_status"] == "ready"
    assert fake.token_forms[1]["grant_type"] == ["refresh_token"]  # expired soon → refreshed
    assert fake.calls.count(("GET", "/books/v3/invoices")) == 3  # one 429 retried, two pages

    s2 = analyst.post(f"/api/connectors/{cid}/sync", json={"kind": "sales_register"}).json()
    assert s2["status"] == "unchanged" and s2["dataset_version_id"] == s1j["dataset_version_id"]
    fake.invoices[0]["total"] = 106
    s3 = analyst.post(f"/api/connectors/{cid}/sync", json={"kind": "sales_register"}).json()
    assert s3["status"] == "succeeded" and s3["dataset_version_id"] != s1j["dataset_version_id"]
    ds_id = viewer.get(f"/api/connectors/{cid}").json()["datasets"]["sales_register"]
    versions = viewer.get(f"/api/datasets/{ds_id}").json()
    assert versions["latest_version"]["version_number"] == 2

    fake.refuse = True
    s4 = analyst.post(f"/api/connectors/{cid}/sync", json={"kind": "sales_register"}).json()
    assert s4["status"] == "failed" and "refused" in s4["message"]
    assert viewer.get(f"/api/connectors/{cid}").json()["status"] == "error"

    assert analyst.post(f"/api/connectors/{cid}/disconnect").status_code == 403
    off = admin.post(f"/api/connectors/{cid}/disconnect")
    assert off.status_code == 200 and off.json()["has_credentials"] is False
    assert (
        analyst.post(f"/api/connectors/{cid}/sync", json={"kind": "sales_register"}).status_code
        == 422
    )


def test_odoo_api_key(
    tenant_a: Tenant, db: Session, enabled: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[dict[str, Any]] = []

    def odoo(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "acme.odoo.com" and request.url.path == "/jsonrpc"
        payload = json.loads(request.content)
        seen.append(payload["params"])
        if payload["params"]["method"] == "authenticate":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": 7})
        args = payload["params"]["args"]
        assert args[1] == 7 and args[3] == "res.partner" and args[4] == "search_read"
        rows = [
            {"id": 11, "name": "Synthetic Supplier", "vat": "100000000000003", "email": False},
            {"id": 12, "name": "Second Supplier", "vat": False, "email": "ap@example.org"},
        ]
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": rows})

    _mock(monkeypatch, odoo)
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    entity = make_entity(db, tenant_a)
    body: dict[str, Any] = {
        "entity_id": str(entity.id),
        "provider": "odoo",
        "name": "Syn Odoo",
        "config": {"base_url": "https://acme.odoo.com/", "database": "acme", "username": "ap"},
        "api_key": API_KEY,
    }
    for url in (
        "http://acme.odoo.com",
        "https://acme.odoo.com.evil.example",
        "https://u:p@acme.odoo.com",
    ):
        r = admin.post(
            "/api/connectors", json={**body, "config": {**body["config"], "base_url": url}}
        )
        assert r.status_code == 422, url
    assert admin.post("/api/connectors", json={**body, "api_key": None}).status_code == 422
    r = admin.post("/api/connectors", json=body)
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    assert r.json()["config"]["base_url"] == "https://acme.odoo.com" and API_KEY not in r.text
    assert admin.post(f"/api/connectors/{cid}/authorize").status_code == 422
    t = admin.post(f"/api/connectors/{cid}/test")
    assert t.status_code == 200 and t.json()["status"] == "connected"
    s = admin.post(f"/api/connectors/{cid}/sync", json={"kind": "supplier_master"}).json()
    assert s["status"] == "succeeded" and s["rows"] == 2 and s["dataset_version_status"] == "ready"
    assert seen[0]["args"][2] == API_KEY  # sent to the provider, never echoed back


def test_http_retries_then_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "connector_max_retries", 2)
    monkeypatch.setattr(get_settings(), "connector_min_interval_ms", 0)
    _mock(monkeypatch, lambda request: httpx.Response(503))
    slept: list[float] = []
    with conn.Http(sleep=slept.append) as http, pytest.raises(conn.ConnectorError, match="503"):
        http.request("GET", "https://example.org/x")
    assert http.requests == 3 and slept == [1, 2]


def test_production_guard_checks_connectors() -> None:
    with pytest.raises(ConfigError, match="ZOHO_CLIENT_ID"):
        Settings(
            _env_file=None,  # type: ignore[call-arg]
            app_env="production",
            connectors_enabled=True,
            zoho_client_id="only-the-id",
        ).validate_for_production()
