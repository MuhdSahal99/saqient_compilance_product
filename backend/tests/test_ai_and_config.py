from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from app.ai import (
    MOCK_PREFIX,
    AIDisabledError,
    DisabledProvider,
    MockProvider,
    OpenAICompatibleProvider,
    get_provider,
)
from app.ai.citations import Citation, normalise_quote, validate_citations
from app.config import ConfigError, Settings
from app.models import Role, SourceBlock
from tests.conftest import Tenant, login, ready_version_id, upload

FIXTURES = Path(__file__).parent / "fixtures" / "prompt_injection"


def test_ai_disabled_by_default() -> None:
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.ai_enabled is False and s.ai_provider == "disabled"
    provider = get_provider(s)
    assert isinstance(provider, DisabledProvider)
    with pytest.raises(AIDisabledError):
        provider.complete("system", "prompt")


def test_ai_status_endpoint_and_review_work_without_ai(tenant_a: Tenant) -> None:
    client = login(tenant_a.users[Role.REVIEWER])
    status = client.get("/api/ai/status").json()
    assert status["enabled"] is False and status["available_features"] == []
    vid = ready_version_id(client)
    r = client.post(
        "/api/reviews",
        json={
            "title": "No AI",
            "document_version_id": vid,
            "checklist_version_id": str(tenant_a.checklist_version.id),
        },
    )  # type: ignore[union-attr]
    assert r.json()["latest_run"]["job"]["status"] == "completed"


def test_mock_provider_only_in_dev_and_labelled() -> None:
    dev = Settings(
        _env_file=None,
        app_env="development",
        ai_enabled=True,  # type: ignore[call-arg]
        ai_provider="mock",
    )
    out = get_provider(dev).complete("s", "p")
    assert out.text.startswith(MOCK_PREFIX)
    prod = Settings(
        _env_file=None,
        app_env="production",
        ai_enabled=True,  # type: ignore[call-arg]
        ai_provider="mock",
    )
    with pytest.raises(ConfigError):
        MockProvider(prod)


def test_external_endpoint_must_be_allowlisted() -> None:
    base = dict(_env_file=None, ai_enabled=True, ai_provider="openai_compatible", ai_model="m")
    with pytest.raises(ConfigError):
        OpenAICompatibleProvider(Settings(**base, ai_base_url="https://evil.example/v1"))  # type: ignore[arg-type]
    with pytest.raises(ConfigError):
        OpenAICompatibleProvider(
            Settings(
                **base,
                ai_base_url="http://models.internal/v1",  # type: ignore[arg-type]
                ai_allowed_hosts="models.internal",
            )
        )
    ok = OpenAICompatibleProvider(
        Settings(
            **base,
            ai_base_url="https://models.internal/v1",  # type: ignore[arg-type]
            ai_allowed_hosts="models.internal",
        )
    )
    assert ok.name == "openai_compatible"
    # Plain http only with the explicit private-network switch, and still allowlisted.
    private = OpenAICompatibleProvider(
        Settings(
            **base,
            ai_base_url="http://inference:8000/v1",  # type: ignore[arg-type]
            ai_allowed_hosts="inference",
            ai_allow_insecure_http=True,
        )
    )
    assert private.name == "openai_compatible"
    with pytest.raises(ConfigError):
        OpenAICompatibleProvider(
            Settings(
                **base,
                ai_base_url="http://other:8000/v1",  # type: ignore[arg-type]
                ai_allowed_hosts="inference",
                ai_allow_insecure_http=True,
            )
        )


def test_jais_falcon_require_verified_interface() -> None:
    for name in ("jais", "falcon"):
        s = Settings(_env_file=None, ai_enabled=True, ai_provider=name)  # type: ignore[call-arg]
        with pytest.raises(ConfigError, match="VERIFIED"):
            get_provider(s)


def test_production_rejects_insecure_defaults() -> None:
    with pytest.raises(ConfigError) as exc:
        Settings(_env_file=None, app_env="production", demo_mode=True).validate_for_production()  # type: ignore[call-arg]
    msg = str(exc.value)
    assert "SECRET_KEY" in msg and "DEMO_MODE" in msg and "COOKIE_SECURE" in msg
    assert "FIELD_ENCRYPTION_KEY" in msg
    assert "MAIL_BACKEND" in msg and "APP_BASE_URL" in msg
    with pytest.raises(ConfigError, match="SMTP_HOST"):
        Settings(
            _env_file=None, app_env="production", mail_backend="smtp"
        ).validate_for_production()  # type: ignore[call-arg]
    Settings(
        _env_file=None,
        app_env="production",
        secret_key="x" * 40,  # type: ignore[call-arg]
        field_encryption_key="QUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=",  # 32 bytes, test only
        cookie_secure=True,
        celery_task_always_eager=False,
        mail_backend="smtp",
        smtp_host="smtp.example.org",
        app_base_url="https://app.example.org",
    ).validate_for_production()


def test_citation_validation(tenant_a: Tenant, tenant_b: Tenant, db) -> None:  # type: ignore[no-untyped-def]
    a = login(tenant_a.users[Role.ANALYST])
    b = login(tenant_b.users[Role.ANALYST])
    upload(a, (FIXTURES / "fake_citation.txt").read_bytes(), "a.txt")
    upload(b, (FIXTURES / "ignore_instructions.txt").read_bytes(), "b.txt")
    block_a = db.scalar(
        select(SourceBlock).where(
            SourceBlock.org_id == tenant_a.org.id, SourceBlock.text.contains("retention")
        )
    )
    block_b = db.scalar(select(SourceBlock).where(SourceBlock.org_id == tenant_b.org.id))
    results = validate_citations(
        db,
        tenant_a.org.id,
        [
            Citation(str(block_a.id), "data  RETENTION periods are listed"),  # normalised match
            Citation(str(block_a.id), "retention is unlimited"),  # fabricated quote
            Citation(str(block_b.id), block_b.text[:20]),  # other tenant's block
            Citation("not-a-uuid", "x"),
        ],
    )
    assert [r.status for r in results] == ["valid", "unsupported", "unsupported", "unsupported"]
    assert results[0].ref == block_a.ref
    assert results[2].reason == "block not found or not accessible"


def test_arabic_normalisation() -> None:
    assert normalise_quote("مَالِك  السياسـة") == normalise_quote("مالك السياسة")


def test_prompt_injection_text_has_no_effect_on_deterministic_review(tenant_a: Tenant) -> None:
    client = login(tenant_a.users[Role.REVIEWER])
    data = (FIXTURES / "ignore_instructions.txt").read_bytes()
    vid = ready_version_id(client, data=data, filename="inject.txt")
    review = client.post(
        "/api/reviews",
        json={
            "title": "Injection",
            "document_version_id": vid,
            "checklist_version_id": str(tenant_a.checklist_version.id),
        },
    ).json()  # type: ignore[union-attr]
    results = {
        r["requirement_code"]: r["outcome"]
        for r in client.get(f"/api/reviews/{review['id']}/results").json()
    }
    # "fully compliant" in the text is flagged as prohibited language, not obeyed.
    assert results["DEMO-05"] == "match_found"
    assert results["DEMO-03"] == "no_match_found"
    fs = client.get("/api/findings", params={"review_id": review["id"]}).json()["items"]
    assert all(f["status"] == "proposed" for f in fs)


def test_google_auth_sends_short_lived_token(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    from app.ai import GoogleToken

    url = "https://me-central2-aiplatform.googleapis.com/v1/projects/p/locations/me-central2/endpoints/1"
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        ai_enabled=True,
        ai_provider="openai_compatible",
        ai_model="falcon",
        ai_base_url=url,
        ai_allowed_hosts="me-central2-aiplatform.googleapis.com",
        ai_auth="google",
    )
    monkeypatch.setattr(GoogleToken, "get", lambda self: "short-lived-token")
    seen: dict[str, object] = {}

    def fake_post(target: str, **kwargs: object) -> httpx.Response:
        seen["url"], seen["headers"] = target, kwargs["headers"]
        body = {"id": "r1", "model": "falcon", "choices": [{"message": {"content": "{}"}}]}
        return httpx.Response(200, json=body, request=httpx.Request("POST", target))

    monkeypatch.setattr(httpx, "post", fake_post)
    out = OpenAICompatibleProvider(settings).complete("system", "prompt")
    assert out.text == "{}" and out.model == "falcon"
    assert seen["url"] == url + "/chat/completions"
    assert seen["headers"] == {"Authorization": "Bearer short-lived-token"}

    with pytest.raises(ConfigError):
        OpenAICompatibleProvider(settings.model_copy(update={"ai_api_key": "static"}))


def test_google_auth_failure_is_a_safe_provider_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.ai import AIProviderError, GoogleToken

    def boom(self: GoogleToken) -> str:
        raise RuntimeError("could not load key file /secret/path.json")

    monkeypatch.setattr(GoogleToken, "get", boom)
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        ai_enabled=True,
        ai_provider="openai_compatible",
        ai_model="falcon",
        ai_base_url="https://vertex.example/v1",
        ai_allowed_hosts="vertex.example",
        ai_auth="google",
    )
    with pytest.raises(AIProviderError) as err:
        OpenAICompatibleProvider(settings).complete("s", "p")
    assert "secret" not in str(err.value) and "RuntimeError" in str(err.value)


def test_google_api_key_uses_its_own_header(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    base = dict(
        _env_file=None,
        ai_enabled=True,
        ai_provider="openai_compatible",
        ai_model="falcon",
        ai_base_url="https://aiplatform.googleapis.com/v1/projects/p/locations/l/endpoints/e",
        ai_allowed_hosts="aiplatform.googleapis.com",
        ai_auth="google_api_key",
    )
    with pytest.raises(ConfigError):
        OpenAICompatibleProvider(Settings(**base))  # type: ignore[arg-type]
    seen: dict[str, object] = {}

    def fake_post(target: str, **kwargs: object) -> httpx.Response:
        seen["headers"] = kwargs["headers"]
        body = {"choices": [{"message": {"content": "{}"}}]}
        return httpx.Response(200, json=body, request=httpx.Request("POST", target))

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = OpenAICompatibleProvider(Settings(**base, ai_api_key="AIza-test"))  # type: ignore[arg-type]
    provider.complete("s", "p")
    assert seen["headers"] == {"x-goog-api-key": "AIza-test"}
