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
    Settings(
        _env_file=None,
        app_env="production",
        secret_key="x" * 40,  # type: ignore[call-arg]
        cookie_secure=True,
        celery_task_always_eager=False,
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
