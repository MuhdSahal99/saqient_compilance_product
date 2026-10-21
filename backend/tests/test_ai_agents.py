"""Phase G: Gemini provider, multi-agent tasks, deterministic guards and human decisions."""

from __future__ import annotations

import json
import uuid
from datetime import date
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import ai
from app.ai.agents import base
from app.ai.gemini import GeminiProvider
from app.config import ConfigError, Settings, get_settings
from app.models import (
    AITask,
    AuditEvent,
    ChecklistState,
    LetterPoint,
    Role,
    Rule,
    RulePack,
    RulePackVersion,
    RuleValueType,
    RuleVerification,
)
from tests.conftest import ApiClient, Tenant, login, ready_version_id
from tests.test_audit_risks import programme
from tests.test_datasets import make_entity
from tests.test_engagements import new_engagement

# ---------------------------------------------------------------- Gemini provider


def _gemini_settings(**kw: Any) -> Settings:
    base_kw: dict[str, Any] = {
        "app_env": "test",
        "ai_enabled": True,
        "ai_provider": "gemini",
        "gemini_api_key": "test-key-not-real",
    }
    return Settings(**(base_kw | kw))


def _answer(text: str, **extra: Any) -> dict[str, Any]:
    return {
        "candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}],
        "usageMetadata": {"promptTokenCount": 120, "candidatesTokenCount": 30},
        "modelVersion": "gemini-3.5-flash-lite-001",
        **extra,
    }


def test_gemini_tiers_default_and_override() -> None:
    s = _gemini_settings()
    assert s.ai_model_for("reasoning") == "gemini-3.8-flash"
    assert s.ai_model_for("fast") == "gemini-3.5-flash-lite"
    s = _gemini_settings(ai_model_reasoning="gemini-4-argon", ai_model_fast="gemini-3.6-flash")
    assert s.ai_model_for("reasoning") == "gemini-4-argon"
    assert s.ai_model_for("fast") == "gemini-3.6-flash"
    # AI_API_KEY works too; a missing key or another host is refused.
    assert _gemini_settings(gemini_api_key="", ai_api_key="k").gemini_key == "k"
    with pytest.raises(ConfigError, match="GEMINI_API_KEY"):
        _gemini_settings(gemini_api_key="").validate_ai()
    with pytest.raises(ConfigError, match="GEMINI_BASE_URL"):
        _gemini_settings(gemini_base_url="https://evil.example/v1beta").validate_ai()
    p = ai.get_provider(_gemini_settings(), "reasoning")
    assert isinstance(p, GeminiProvider) and p.model == "gemini-3.8-flash"
    assert "test-key-not-real" not in repr(_gemini_settings())


def test_gemini_request_shape_and_parsing() -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        parts = [{"text": "thinking...", "thought": True}, {"text": '{"ok": true}'}]
        body = _answer("")
        body["candidates"][0]["content"]["parts"] = parts
        return httpx.Response(200, json=body)

    p = GeminiProvider(_gemini_settings(), "fast", transport=httpx.MockTransport(handle))
    c = p.complete("system text", "prompt text", max_tokens=500)
    assert c.text == '{"ok": true}' and c.provider == "gemini"
    assert c.model == "gemini-3.5-flash-lite" and c.model_version == "gemini-3.5-flash-lite-001"
    assert (c.input_tokens, c.output_tokens) == (120, 30)
    req = seen[0]
    assert req.url.host == "generativelanguage.googleapis.com"
    assert req.url.path == "/v1beta/models/gemini-3.5-flash-lite:generateContent"
    assert req.headers["x-goog-api-key"] == "test-key-not-real"
    assert "key" not in str(req.url)  # never in the URL, where proxies log it
    body = json.loads(req.content)
    assert body["systemInstruction"]["parts"][0]["text"] == "system text"
    assert body["contents"][0]["parts"][0]["text"] == "prompt text"
    gen = body["generationConfig"]
    assert gen["responseMimeType"] == "application/json"
    assert gen["thinkingConfig"] == {"thinkingLevel": "low"}
    assert gen["maxOutputTokens"] == 500 + 1024


def test_gemini_retries_rate_limits_then_fails_safely() -> None:
    calls = {"n": 0}

    def flaky(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"retry-after": "1"}, json={})
        return httpx.Response(200, json=_answer('{"ok": 1}'))

    p = GeminiProvider(_gemini_settings(), "fast", transport=httpx.MockTransport(flaky))
    slept: list[float] = []
    p._sleep = slept.append
    assert p.complete("s", "p").text == '{"ok": 1}'
    assert calls["n"] == 2 and slept == [1.0]

    def bad(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "API key test-key-not-real bad"}})

    p = GeminiProvider(_gemini_settings(), "fast", transport=httpx.MockTransport(bad))
    with pytest.raises(ai.AIProviderError) as exc:
        p.complete("s", "p")
    assert str(exc.value) == "Gemini request failed (HTTP 400)."

    def empty(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"candidates": [{"finishReason": "SAFETY"}]})

    p = GeminiProvider(_gemini_settings(), "fast", transport=httpx.MockTransport(empty))
    with pytest.raises(ai.AIProviderError, match="finish reason SAFETY"):
        p.complete("s", "p")


# ---------------------------------------------------------------- guards


def test_number_and_id_guards() -> None:
    evidence = "Expected 1,250.5000 AED, GL ١٢٠٠ AED, difference 50.50"
    assert base.numbers_in(evidence) == {"1250.5", "1200", "50.5"}
    assert base.ungrounded_numbers("Difference of 50.5 between 1250.50 and 1,200.", evidence) == []
    assert base.ungrounded_numbers("Check 3 items; the rate is 15% on 9,999.", evidence) == [
        "15",
        "9999",
    ]
    assert base.known_ids(["R1", "R9", "Q1", "R1"], {"R1", "Q1"}) == (["R1", "Q1"], 1)
    assert base.fence("DOC", "a >>> b <<<") == "<<<DOC\na ››› b ‹‹‹\nDOC>>>"


# ---------------------------------------------------------------- tasks end to end (mock)


@pytest.fixture
def ai_on(monkeypatch: pytest.MonkeyPatch, tenant_a: Tenant) -> ApiClient:
    s = get_settings()
    monkeypatch.setattr(s, "ai_enabled", True)
    monkeypatch.setattr(s, "ai_provider", "mock")
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    assert admin.put("/api/org/ai-settings", json={"opted_in": True}).status_code == 200
    return admin


def _task(client: ApiClient, **body: Any) -> httpx.Response:
    return client.post("/api/ai/tasks", json=body)


def test_tasks_need_the_deployment_and_the_org_opt_in(tenant_a: Tenant) -> None:
    analyst = login(tenant_a.users[Role.ANALYST])
    r = _task(analyst, kind="pack_qa", question="What is the filing deadline?")
    assert r.status_code == 409 and "not enabled" in r.json()["detail"]
    assert analyst.get("/api/ai/agents").json() == []


def test_contract_scan_with_mock(ai_on: ApiClient, tenant_a: Tenant, db: Session) -> None:
    analyst = login(tenant_a.users[Role.ANALYST])
    vid = ready_version_id(analyst)
    agents = analyst.get("/api/ai/agents").json()
    assert {a["name"]: a["tier"] for a in agents}["contract_tax"] == "reasoning"
    assert {a["name"]: a["tier"] for a in agents}["critic"] == "fast"

    r = _task(analyst, kind="contract_tax", subject_id=vid)
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["status"] == "ready" and t["is_mock"] is True and t["job"]["status"] == "completed"
    assert [s["agent"] for s in t["steps"]] == ["contract_tax", "critic"]
    assert {s["tier"] for s in t["steps"]} == {"reasoning", "fast"}
    item = t["output"]["items"][0]
    assert item["summary"].startswith(ai.MOCK_PREFIX) and item["checked"] is True
    # Evidence shown is cut from stored block text.
    assert item["evidence"][0]["block_id"] and item["evidence"][0]["quote"]
    assert t["warnings"][0].startswith("Mock provider output")
    listed = analyst.get("/api/ai/tasks", params={"subject_id": vid}).json()
    assert [x["id"] for x in listed] == [t["id"]]
    assert db.scalar(
        select(AuditEvent).where(
            AuditEvent.org_id == tenant_a.org.id, AuditEvent.action == "ai.task_requested"
        )
    )


def test_finding_explanation_and_decisions(
    ai_on: ApiClient, tenant_a: Tenant, tenant_b: Tenant
) -> None:
    analyst = login(tenant_a.users[Role.ANALYST])
    reviewer = login(tenant_a.users[Role.REVIEWER])
    viewer = login(tenant_a.users[Role.VIEWER])
    fid = _finding(analyst, tenant_a)

    assert _task(viewer, kind="finding_explain", subject_id=fid).status_code == 403
    t = _task(analyst, kind="finding_explain", subject_id=fid).json()
    assert t["status"] == "ready" and t["output"]["explanation_ar"]
    assert [s["agent"] for s in t["steps"]] == ["finding_explainer", "critic"]

    # Analysts cannot decide; reviewers can, once.
    assert analyst.post(f"/api/ai/tasks/{t['id']}/accept", json={}).status_code == 403
    ok = reviewer.post(f"/api/ai/tasks/{t['id']}/accept", json={"note": "Useful"})
    assert ok.status_code == 200 and ok.json()["status"] == "accepted"
    assert ok.json()["decided_by_name"]
    again = reviewer.post(f"/api/ai/tasks/{t['id']}/dismiss", json={})
    assert again.status_code == 409

    # Other tenants see nothing and cannot use the ids.
    other = login(tenant_b.users[Role.REVIEWER])
    assert other.get(f"/api/ai/tasks/{t['id']}").status_code == 404
    assert other.post(f"/api/ai/tasks/{t['id']}/dismiss", json={}).status_code == 404
    assert _task(other, kind="finding_explain", subject_id=fid).status_code == 404
    assert _task(other, kind="finding_explain", subject_id=str(uuid.uuid4())).status_code == 404
    assert other.get("/api/ai/tasks").json() == []


def _finding(client: ApiClient, tenant: Tenant) -> str:
    from tests.test_reviews import start_review

    review = start_review(client, tenant)
    r = client.post(
        f"/api/reviews/{review['id']}/findings",
        json={
            "title": "Synthetic: invoice total differs from lines",
            "description": "Synthetic: total 1,050.00 against line sum 1,000.00.",
            "severity": "medium",
        },
    )
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def test_letter_wording_only_for_confirmed_findings(
    ai_on: ApiClient, tenant_a: Tenant, db: Session
) -> None:
    reviewer = login(tenant_a.users[Role.REVIEWER])
    analyst = login(tenant_a.users[Role.ANALYST])
    entity = make_entity(db, tenant_a)
    eid = new_engagement(reviewer, entity.id).json()["id"]
    pid = programme(reviewer)
    vid = ready_version_id(analyst)
    rid = analyst.post(
        "/api/reviews",
        json={"title": "Synthetic", "checklist_version_id": pid, "document_version_id": vid},
    ).json()["id"]
    assert analyst.post(f"/api/engagements/{eid}/reviews/{rid}").status_code == 204
    fid = analyst.post(
        f"/api/reviews/{rid}/findings",
        json={"title": "Synthetic cut-off error", "description": "Synthetic", "severity": "high"},
    ).json()["id"]
    d = reviewer.post(
        f"/api/findings/{fid}/decision", json={"decision": "confirmed", "rationale": "Synthetic"}
    )
    assert d.status_code == 200, d.text
    point = analyst.post(f"/api/engagements/{eid}/letter/refresh").json()["points"][0]

    t = _task(analyst, kind="letter_draft", subject_id=point["id"], language="ar").json()
    assert t["status"] == "ready" and t["language"] == "ar"
    assert t["output"]["recommendation"].startswith(ai.MOCK_PREFIX)
    ok = reviewer.post(f"/api/ai/tasks/{t['id']}/accept", json={})
    assert ok.status_code == 200, ok.text
    db.expire_all()
    p = db.get(LetterPoint, uuid.UUID(point["id"]))
    assert p is not None and p.recommendation == t["output"]["recommendation"]

    # Once the finding is no longer confirmed, no drafting.
    reopen = reviewer.post(
        f"/api/findings/{fid}/decision", json={"decision": "dismissed", "rationale": "Synthetic"}
    )
    if reopen.status_code == 200:
        r = _task(analyst, kind="letter_draft", subject_id=point["id"])
        assert r.status_code == 409 and "confirmed" in r.json()["detail"]


def _verified_rule(db: Session, tenant: Tenant, *, verified: bool, published: bool) -> Rule:
    pack = RulePack(
        org_id=tenant.org.id, name=f"Synthetic pack {uuid.uuid4().hex[:6]}", jurisdiction="XX"
    )
    db.add(pack)
    db.flush()
    v = RulePackVersion(
        org_id=tenant.org.id,
        rule_pack_id=pack.id,
        version_number=1,
        state=ChecklistState.PUBLISHED if published else ChecklistState.DRAFT,
    )
    db.add(v)
    db.flush()
    rule = Rule(
        org_id=tenant.org.id,
        rule_pack_version_id=v.id,
        rule_key="synthetic.return_due_days",
        title="Synthetic return filing due days",
        value_type=RuleValueType.INTEGER,
        value="28",
        unit="days",
        effective_from=date(2026, 1, 1),
        verification_status=RuleVerification.VERIFIED if verified else RuleVerification.DRAFT,
    )
    db.add(rule)
    db.commit()
    return rule


def test_pack_qa_uses_verified_content_only(
    ai_on: ApiClient, tenant_a: Tenant, db: Session
) -> None:
    analyst = login(tenant_a.users[Role.ANALYST])
    _verified_rule(db, tenant_a, verified=False, published=True)  # draft: never offered
    t = _task(analyst, kind="pack_qa", question="How many days to file the return?").json()
    assert t["status"] == "ready" and t["output"]["insufficient"] is True
    assert [s["agent"] for s in t["steps"]] == ["router"]  # no answer without content
    accept = login(tenant_a.users[Role.REVIEWER]).post(f"/api/ai/tasks/{t['id']}/accept", json={})
    assert accept.status_code == 409

    rule = _verified_rule(db, tenant_a, verified=True, published=True)
    t = _task(analyst, kind="pack_qa", question="How many days to file the return?").json()
    assert t["output"]["insufficient"] is False
    assert [s["agent"] for s in t["steps"]] == ["router", "pack_qa", "critic"]
    assert t["output"]["sources"] == [
        {
            "type": "rule",
            "id": str(rule.id),
            "key": rule.rule_key,
            "title": rule.title,
            "label": "R1",
        }
    ]
    # Arabic question: the router reports the language.
    t = _task(analyst, kind="pack_qa", question="كم يوما لتقديم الإقرار return").json()
    assert t["output"]["language"] == "ar"
    assert _task(analyst, kind="pack_qa", question="   ").status_code == 409
    assert _task(analyst, kind="pack_qa", question="x" * 1001).status_code == 422


# ---------------------------------------------------------------- guards in the pipeline


class Scripted:
    """A provider that answers from a script keyed by the agent's output schema."""

    name = "mock"
    model = "scripted"

    def __init__(self, answers: dict[str, Any]) -> None:
        self.answers = answers

    def complete(self, system: str, prompt: str, *, max_tokens: int | None = None) -> ai.Completion:
        schema = system.rsplit("Output schema: ", 1)[-1].strip()
        value = self.answers[schema]
        if isinstance(value, Exception):
            raise value
        text = value(prompt) if callable(value) else json.dumps(value)
        return ai.Completion(text, "mock", "scripted", "scripted-1", 10, 5)


def _script(monkeypatch: pytest.MonkeyPatch, answers: dict[str, Any]) -> None:
    monkeypatch.setattr(ai, "get_provider", lambda settings, tier="fast": Scripted(answers))


def test_guards_drop_fabricated_quotes_and_flag_numbers(
    ai_on: ApiClient, tenant_a: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    analyst = login(tenant_a.users[Role.ANALYST])
    fid = _finding(analyst, tenant_a)
    vid = ready_version_id(
        analyst, data=b"Synthetic supply agreement. The supplier charges VAT on all fees."
    )
    _script(
        monkeypatch,
        {
            "contract_tax": {
                "items": [
                    {
                        "topic": "vat_treatment",
                        "cue": "zero_rated_cue",
                        "summary": "Invented.",
                        "citations": [{"block": "B1", "quote": "this text is not in the file"}],
                    },
                    {
                        "topic": "related_party",
                        "cue": "made_up_cue",
                        "summary": "Bad cue.",
                        "citations": [{"block": "B1", "quote": "x"}],
                    },
                ]
            },
            "finding_explain": {
                "explanation_en": "The total of 1,050.00 is 50 above the lines; rate 15%.",
                "explanation_ar": "شرح",
                "evidence_used": ["E7"],
            },
            "critic": {"verdicts": [{"claim": "C1", "supported": False, "reason": "adds rate"}]},
        },
    )
    t = _task(analyst, kind="contract_tax", subject_id=vid).json()
    assert t["output"]["items"] == []
    assert any("did not match the document" in w for w in t["warnings"])

    t = _task(analyst, kind="finding_explain", subject_id=fid).json()
    out = t["output"]
    assert out["evidence_used"] == [] and out["checked"] is False
    assert any("not in the finding or its evidence: 15" in w for w in t["warnings"])
    assert any("could not match part of this draft" in w for w in t["warnings"])
    assert all(s["model_version"] == "scripted-1" for s in t["steps"])


def test_provider_outage_fails_the_task_safely(
    ai_on: ApiClient, tenant_a: Tenant, monkeypatch: pytest.MonkeyPatch, db: Session
) -> None:
    analyst = login(tenant_a.users[Role.ANALYST])
    fid = _finding(analyst, tenant_a)
    _script(
        monkeypatch, {"finding_explain": ai.AIProviderError("Gemini request failed (HTTP 503).")}
    )
    t = _task(analyst, kind="finding_explain", subject_id=fid).json()
    assert t["status"] == "failed" and t["job"]["status"] == "failed"
    assert t["error"] == "Processing failed after repeated attempts."
    # Each attempt's agent call is recorded, with the safe provider message.
    assert [s["status"] for s in t["steps"]] == ["provider_error", "provider_error"]
    # The finding itself is untouched and a new request is allowed.
    assert db.get(AITask, uuid.UUID(t["id"])) is not None
    _script(
        monkeypatch,
        {
            "finding_explain": {"explanation_en": "Plain.", "explanation_ar": "واضح"},
            "critic": {"verdicts": []},
        },
    )
    assert _task(analyst, kind="finding_explain", subject_id=fid).json()["status"] == "ready"
