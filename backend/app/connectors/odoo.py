"""Odoo (JSON-RPC with a user API key; read-only ``search_read`` calls only).

Models and fields follow Odoo's public external API documentation and are unverified
against a live database. The base URL must be https and its host must end with one
of ``ODOO_ALLOWED_HOST_SUFFIXES``, so a user cannot point the server at arbitrary hosts.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from app.config import get_settings
from app.connectors import ConnectorAuthError, ConnectorError, FetchResult, Http
from app.models import ConnectorProvider, DatasetKind

# (model, domain, canonical column → source field)
MODELS: dict[DatasetKind, tuple[str, list[Any], dict[str, str]]] = {
    DatasetKind.SALES_REGISTER: (
        "account.move",
        [["move_type", "=", "out_invoice"], ["state", "=", "posted"]],
        {
            "invoice_number": "name",
            "invoice_date": "invoice_date",
            "customer_name": "partner_id",
            "net_amount": "amount_untaxed",
            "tax_amount": "amount_tax",
            "gross_amount": "amount_total",
            "currency": "currency_id",
        },
    ),
    DatasetKind.PURCHASE_REGISTER: (
        "account.move",
        [["move_type", "=", "in_invoice"], ["state", "=", "posted"]],
        {
            "invoice_number": "name",
            "invoice_date": "invoice_date",
            "supplier_name": "partner_id",
            "net_amount": "amount_untaxed",
            "tax_amount": "amount_tax",
            "gross_amount": "amount_total",
            "currency": "currency_id",
        },
    ),
    DatasetKind.SUPPLIER_MASTER: (
        "res.partner",
        [["supplier_rank", ">", 0]],
        {"party_id": "id", "name": "name", "trn": "vat", "email": "email"},
    ),
    DatasetKind.AP_PAYMENTS: (
        "account.payment",
        [["partner_type", "=", "supplier"], ["payment_type", "=", "outbound"]],
        {
            "payment_id": "name",
            "payment_date": "date",
            "vendor_name": "partner_id",
            "amount": "amount",
            "currency": "currency_id",
            "description": "ref",
        },
    ),
}
PAGE = 500


def check_base_url(url: str) -> str:
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host or parts.username or parts.password:
        raise ConnectorError("The Odoo address must be an https URL.")
    if parts.port not in (None, 443):
        raise ConnectorError("The Odoo address must use the standard https port.")
    allowed = get_settings().odoo_allowed_suffix_list
    if not any(
        host == s.lstrip(".") or host.endswith(s if s.startswith(".") else f".{s}") for s in allowed
    ):
        raise ConnectorError("That Odoo host is not on the allowed list for this installation.")
    return f"https://{host}"


def _value(v: Any) -> str:
    """Many-to-one fields come back as [id, display name]; false means empty."""
    if v is False or v is None:
        return ""
    if isinstance(v, list) and len(v) == 2:
        return str(v[1])
    return str(v)


class OdooAdapter:
    provider: ConnectorProvider = ConnectorProvider.ODOO
    label: str = "Odoo"
    auth: str = "api_key"
    kinds: tuple[DatasetKind, ...] = tuple(MODELS)
    scopes: tuple[str, ...] = ("search_read",)

    def configured(self) -> bool:
        return True

    def authorize_url(self, state: str, challenge: str, redirect_uri: str) -> str:
        raise ConnectorError("Odoo uses an API key, not OAuth.")

    def exchange(self, http: Http, code: str, verifier: str, redirect_uri: str) -> dict[str, Any]:
        raise ConnectorError("Odoo uses an API key, not OAuth.")

    def refresh(self, http: Http, secret: dict[str, Any]) -> dict[str, Any]:
        return secret

    def _call(
        self, http: Http, config: dict[str, Any], service: str, method: str, args: list[Any]
    ) -> Any:
        base = check_base_url(str(config.get("base_url", "")))
        body = http.json(
            "POST",
            f"{base}/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "method": "call",
                "params": {"service": service, "method": method, "args": args},
                "id": 1,
            },
        )
        if not isinstance(body, dict) or "error" in body:
            raise ConnectorError("Odoo returned an error for this request.")
        return body.get("result")

    def connect(self, http: Http, secret: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        uid = self._call(
            http,
            config,
            "common",
            "authenticate",
            [config.get("database"), config.get("username"), secret.get("api_key"), {}],
        )
        if not isinstance(uid, int) or isinstance(uid, bool) or uid <= 0:
            raise ConnectorAuthError("Odoo refused the database, user or API key.")
        return {**config, "uid": uid}

    def fetch(
        self,
        http: Http,
        kind: DatasetKind,
        secret: dict[str, Any],
        config: dict[str, Any],
        since: Any = None,
    ) -> FetchResult:
        if kind not in MODELS:
            raise ConnectorError(f"Odoo does not supply {kind.value.replace('_', ' ')}.")
        uid = config.get("uid")
        if not uid:
            raise ConnectorError("Test the Odoo connection first.")
        model, domain, fields = MODELS[kind]
        out = FetchResult(columns=list(fields))
        for page in range(get_settings().connector_max_pages):
            rows = self._call(
                http,
                config,
                "object",
                "execute_kw",
                [
                    config.get("database"),
                    uid,
                    secret.get("api_key"),
                    model,
                    "search_read",
                    [domain],
                    {
                        "fields": sorted(set(fields.values())),
                        "limit": PAGE,
                        "offset": page * PAGE,
                        "order": "id",
                    },
                ],
            )
            if not isinstance(rows, list):
                raise ConnectorError("Odoo returned an unexpected response.")
            for item in rows:
                out.rows.append({col: _value(item.get(src)) for col, src in fields.items()})
            if len(rows) < PAGE:
                return out
        raise ConnectorError("Too many pages; narrow the request or raise the page limit.")
