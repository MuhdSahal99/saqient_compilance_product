"""Zoho Books (OAuth 2.0 with PKCE, read scopes only).

Endpoints and field names follow Zoho's public Books API v3 documentation and are
unverified against a live account. The data-centre URLs are settings
(``ZOHO_ACCOUNTS_URL``, ``ZOHO_API_URL``) because Zoho runs regional data centres.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from app.config import get_settings
from app.connectors import ConnectorAuthError, ConnectorError, FetchResult, Http
from app.models import ConnectorProvider, DatasetKind

# (path, list key, extra query, canonical column → source field)
ENDPOINTS: dict[DatasetKind, tuple[str, str, dict[str, str], dict[str, str]]] = {
    DatasetKind.SALES_REGISTER: (
        "/invoices",
        "invoices",
        {},
        {
            "invoice_number": "invoice_number",
            "invoice_date": "date",
            "customer_name": "customer_name",
            "net_amount": "sub_total",
            "tax_amount": "tax_total",
            "gross_amount": "total",
            "currency": "currency_code",
        },
    ),
    DatasetKind.PURCHASE_REGISTER: (
        "/bills",
        "bills",
        {},
        {
            "invoice_number": "bill_number",
            "invoice_date": "date",
            "supplier_name": "vendor_name",
            "net_amount": "sub_total",
            "tax_amount": "tax_total",
            "gross_amount": "total",
            "currency": "currency_code",
        },
    ),
    DatasetKind.SUPPLIER_MASTER: (
        "/contacts",
        "contacts",
        {"contact_type": "vendor"},
        {
            "party_id": "contact_id",
            "name": "contact_name",
            "trn": "tax_reg_no",
            "email": "email",
        },
    ),
    DatasetKind.AP_PAYMENTS: (
        "/vendorpayments",
        "vendorpayments",
        {},
        {
            "payment_id": "payment_id",
            "payment_date": "date",
            "vendor_id": "vendor_id",
            "vendor_name": "vendor_name",
            "invoice_number": "bill_numbers",
            "amount": "amount",
            "currency": "currency_code",
            "description": "reference_number",
        },
    ),
}
SCOPES = (
    "ZohoBooks.settings.READ",
    "ZohoBooks.invoices.READ",
    "ZohoBooks.bills.READ",
    "ZohoBooks.contacts.READ",
    "ZohoBooks.vendorpayments.READ",
)
PER_PAGE = 200


def _expires(payload: dict[str, Any]) -> str:
    seconds = int(payload.get("expires_in") or 3600)
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()


def _value(v: Any) -> str:
    return "" if v is None else str(v)


class ZohoBooksAdapter:
    provider: ConnectorProvider = ConnectorProvider.ZOHO_BOOKS
    label: str = "Zoho Books"
    auth: str = "oauth"
    kinds: tuple[DatasetKind, ...] = tuple(ENDPOINTS)
    scopes: tuple[str, ...] = SCOPES

    def configured(self) -> bool:
        return get_settings().zoho_configured

    def authorize_url(self, state: str, challenge: str, redirect_uri: str) -> str:
        s = get_settings()
        query = {
            "scope": ",".join(SCOPES),
            "client_id": s.zoho_client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        return f"{s.zoho_accounts_url.rstrip('/')}/oauth/v2/auth?{urlencode(query)}"

    def _token(self, http: Http, data: dict[str, str]) -> dict[str, Any]:
        s = get_settings()
        body = http.json(
            "POST",
            f"{s.zoho_accounts_url.rstrip('/')}/oauth/v2/token",
            data={**data, "client_id": s.zoho_client_id, "client_secret": s.zoho_client_secret},
        )
        if not isinstance(body, dict) or "error" in body or not body.get("access_token"):
            raise ConnectorAuthError("Zoho did not issue a token.")
        return body

    def exchange(self, http: Http, code: str, verifier: str, redirect_uri: str) -> dict[str, Any]:
        body = self._token(
            http,
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": verifier,
            },
        )
        if not body.get("refresh_token"):
            raise ConnectorAuthError("Zoho did not issue a refresh token.")
        return {
            "access_token": body["access_token"],
            "refresh_token": body["refresh_token"],
            "expires_at": _expires(body),
        }

    def refresh(self, http: Http, secret: dict[str, Any]) -> dict[str, Any]:
        body = self._token(
            http, {"grant_type": "refresh_token", "refresh_token": secret["refresh_token"]}
        )
        return {**secret, "access_token": body["access_token"], "expires_at": _expires(body)}

    def _headers(self, secret: dict[str, Any]) -> dict[str, str]:
        return {"Authorization": f"Zoho-oauthtoken {secret['access_token']}"}

    def connect(self, http: Http, secret: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        body = http.json(
            "GET",
            f"{get_settings().zoho_api_url.rstrip('/')}/organizations",
            headers=self._headers(secret),
        )
        orgs = body.get("organizations") if isinstance(body, dict) else None
        if not orgs:
            raise ConnectorError("Zoho returned no organisations for this account.")
        chosen = next((o for o in orgs if o.get("is_default_org")), orgs[0])
        return {
            **config,
            "organization_id": str(chosen.get("organization_id", "")),
            "organization_name": str(chosen.get("name", ""))[:200],
        }

    def fetch(
        self,
        http: Http,
        kind: DatasetKind,
        secret: dict[str, Any],
        config: dict[str, Any],
        since: Any = None,
    ) -> FetchResult:
        if kind not in ENDPOINTS:
            raise ConnectorError(f"Zoho Books does not supply {kind.value.replace('_', ' ')}.")
        path, key, extra, fields = ENDPOINTS[kind]
        org = config.get("organization_id")
        if not org:
            raise ConnectorError("Connect the Zoho account first.")
        out = FetchResult(columns=list(fields))
        url = f"{get_settings().zoho_api_url.rstrip('/')}{path}"
        for page in range(1, get_settings().connector_max_pages + 1):
            body = http.json(
                "GET",
                url,
                params={"organization_id": org, "page": page, "per_page": PER_PAGE, **extra},
                headers=self._headers(secret),
            )
            if not isinstance(body, dict) or body.get("code", 0) != 0:
                raise ConnectorError("Zoho returned an error for this request.")
            for item in body.get(key) or []:
                out.rows.append({col: _value(item.get(src)) for col, src in fields.items()})
            if not (body.get("page_context") or {}).get("has_more_page"):
                return out
        raise ConnectorError("Too many pages; narrow the request or raise the page limit.")
