from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.ai import MOCK_PREFIX, AIProviderError, Completion
from app.config import get_settings
from app.models import AuditEvent, Role, SourceBlock
from app.services import ai_suggestions
from tests.conftest import ApiClient, Tenant, login
from tests.test_reviews import findings, start_review

FIXTURES = Path(__file__).parent / "fixtures" / "prompt_injection"


@pytest.fixture
def mock_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "ai_enabled", True)
    monkeypatch.setattr(s, "ai_provider", "mock")


def _use_provider(monkeypatch: pytest.MonkeyPatch, provider: object) -> None:
    monkeypatch.setattr(ai_suggestions.ai, "get_provider", lambda settings: provider)


def _request(client: ApiClient, review_id: str) -> dict:  # type: ignore[type-arg]
    r = client.post(f"/api/reviews/{review_id}/ai-suggestions")
    assert r.status_code == 200, r.text
    return r.json()


def test_disabled_by_default_and_review_unaffected(tenant_a: Tenant) -> None:
    client = login(tenant_a.users[Role.REVIEWER])
    review = start_review(client, tenant_a)
    r = client.post(f"/api/reviews/{review['id']}/ai-suggestions")
    assert r.status_code == 409 and "not enabled" in r.json()["detail"]
    data = client.get(f"/api/reviews/{review['id']}/ai-suggestions").json()
    assert data == {"available": False, "run": None, "suggestions": []}
    assert client.get("/api/ai/status").json()["available_features"] == []


def test_mock_suggestions_are_labelled_and_cite_stored_text(
    tenant_a: Tenant,
    db,  # type: ignore[no-untyped-def]
    mock_ai: None,
) -> None:
    client = login(tenant_a.users[Role.ANALYST])
    status = client.get("/api/ai/status").json()
    assert status["available_features"] == ["review_suggestions"] and status["is_mock"] is True

    review = start_review(client, tenant_a)
    data = _request(client, review["id"])
    assert data["run"]["job"]["status"] == "completed"
    assert data["run"]["is_mock"] is True and data["run"]["provider"] == "mock"
    assert data["run"]["prompt_version"] == ai_suggestions.PROMPT_VERSION
    n_requirements = len(tenant_a.checklist_version.requirements)  # type: ignore[union-attr]
    assert len(data["suggestions"]) == n_requirements
    for s in data["suggestions"]:
        assert s["assessment"] == "unclear" and s["status"] == "pending"
        assert s["summary"].startswith(MOCK_PREFIX)
        assert s["rejected_citations"] == 0
        for e in s["evidence"]:
            block = db.get(SourceBlock, e["block_id"])
            assert block is not None and e["quote"] in " ".join(block.text.split())

    # Deterministic findings were not touched by the AI run.
    before = {f["id"] for f in findings(client, review["id"])}
    assert before and all(f["ai_suggestion_id"] is None for f in findings(client, review["id"]))

    # A second request while none is running starts a new run; the latest is returned.
    again = _request(client, review["id"])
    assert again["run"]["id"] != data["run"]["id"]
    events = db.scalars(
        select(AuditEvent.action).where(AuditEvent.action == "ai.suggestions_requested")
    ).all()
    assert len(events) == 2


class _ForgingProvider:
    name = "mock"

    def __init__(self, foreign_block_id: str | None = None) -> None:
        self.foreign = foreign_block_id

    def complete(self, system: str, prompt: str) -> Completion:
        if "DEMO-01" in prompt:
            return Completion("I cannot answer in JSON.", "mock", "mock", None)
        cites = [
            {"block": "B1", "quote": "this sentence was never in the document"},
            {"block": "B999", "quote": "unknown block label"},
        ]
        if self.foreign:
            cites.append({"block": self.foreign, "quote": "anything"})
        body = {"assessment": "not_addressed", "summary": "Forged.", "citations": cites}
        return Completion(json.dumps(body), "mock", "mock", None)


def test_forged_citations_are_dropped_and_bad_output_marked(
    tenant_a: Tenant,
    tenant_b: Tenant,
    db,  # type: ignore[no-untyped-def]
    mock_ai: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    other = login(tenant_b.users[Role.ANALYST])
    start_review(other, tenant_b)
    foreign = db.scalar(select(SourceBlock).where(SourceBlock.org_id == tenant_b.org.id))
    _use_provider(monkeypatch, _ForgingProvider(str(foreign.id)))

    client = login(tenant_a.users[Role.ANALYST])
    review = start_review(client, tenant_a)
    data = _request(client, review["id"])
    by_code = {s["requirement_code"]: s for s in data["suggestions"]}
    assert by_code["DEMO-01"]["assessment"] == "invalid_output"
    assert by_code["DEMO-01"]["evidence"] == []
    forged = by_code["DEMO-02"]
    assert forged["evidence"] == [] and forged["rejected_citations"] == 3
    # Mock output is always labelled, even if the provider forgot the prefix.
    assert forged["summary"].startswith(MOCK_PREFIX)
    assert any("did not match the document" in w for w in data["run"]["warnings"])


class _FailingProvider:
    name = "mock"

    def complete(self, system: str, prompt: str) -> Completion:
        raise AIProviderError("AI request failed (ConnectError).")


def test_provider_failure_never_breaks_the_review(
    tenant_a: Tenant, mock_ai: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_provider(monkeypatch, _FailingProvider())
    client = login(tenant_a.users[Role.REVIEWER])
    review = start_review(client, tenant_a)
    before = findings(client, review["id"])
    data = _request(client, review["id"])
    assert data["run"]["job"]["status"] == "failed"
    assert data["suggestions"] == []
    assert "Document" not in (data["run"]["job"]["error"] or "")
    after = client.get(f"/api/reviews/{review['id']}").json()
    assert after["status"] == "in_review"
    assert [f["id"] for f in findings(client, review["id"])] == [f["id"] for f in before]


def test_accept_and_reject_need_a_reviewer_and_record_the_model(
    tenant_a: Tenant,
    db,  # type: ignore[no-untyped-def]
    mock_ai: None,
) -> None:
    analyst = login(tenant_a.users[Role.ANALYST])
    viewer = login(tenant_a.users[Role.VIEWER])
    reviewer = login(tenant_a.users[Role.REVIEWER])
    review = start_review(analyst, tenant_a)
    assert viewer.post(f"/api/reviews/{review['id']}/ai-suggestions").status_code == 403
    sugs = _request(analyst, review["id"])["suggestions"]
    first, second = sugs[0], sugs[1]

    assert analyst.post(f"/api/ai-suggestions/{first['id']}/accept", json={}).status_code == 403
    assert viewer.post(f"/api/ai-suggestions/{first['id']}/reject", json={}).status_code == 403

    r = reviewer.post(f"/api/ai-suggestions/{first['id']}/accept", json={"note": "Worth a look"})
    assert r.status_code == 200, r.text
    finding = r.json()
    assert finding["status"] == "proposed"
    assert finding["ai_suggestion_id"] == first["id"]
    assert finding["ai_provider"] == "mock" and finding["ai_model"] == "mock"
    assert finding["requirement_code"] == first["requirement_code"]
    assert finding["description"].startswith(MOCK_PREFIX)
    assert reviewer.post(f"/api/ai-suggestions/{first['id']}/accept", json={}).status_code == 409

    r = reviewer.post(f"/api/ai-suggestions/{second['id']}/reject", json={"note": "Not relevant"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert r.json()["decided_by_name"] == "reviewer a"
    assert reviewer.post(f"/api/ai-suggestions/{second['id']}/accept", json={}).status_code == 409

    listed = reviewer.get(f"/api/reviews/{review['id']}/ai-suggestions").json()["suggestions"]
    states = {s["id"]: (s["status"], s["finding_id"]) for s in listed}
    assert states[first["id"]] == ("accepted", finding["id"])
    assert states[second["id"]] == ("rejected", None)
    actions = set(db.scalars(select(AuditEvent.action)).all())
    assert {"ai.suggestion_accepted", "ai.suggestion_rejected"} <= actions


def test_signed_off_report_records_ai_origin(tenant_a: Tenant, mock_ai: None) -> None:
    reviewer = login(tenant_a.users[Role.REVIEWER])
    review = start_review(reviewer, tenant_a)
    sug = _request(reviewer, review["id"])["suggestions"][0]
    reviewer.post(f"/api/ai-suggestions/{sug['id']}/accept", json={})
    for f in findings(reviewer, review["id"]):
        r = reviewer.post(
            f"/api/findings/{f['id']}/decision",
            json={"decision": "dismissed", "rationale": "Synthetic test decision."},
        )
        assert r.status_code == 200, r.text
    report = reviewer.post(f"/api/reviews/{review['id']}/signoff")
    assert report.status_code == 200, report.text
    rid = report.json()["id"]

    # Signed-off reviews cannot get new suggestions or decisions.
    assert reviewer.post(f"/api/reviews/{review['id']}/ai-suggestions").status_code == 409

    html = reviewer.get(f"/api/reports/{rid}/export", params={"format": "html"}).text
    assert "AI suggestion accepted by a reviewer (mock provider, placeholder text)" in html
    assert "mock AI provider used for testing" in html
    assert "AI analysis was disabled for this review." not in html
    csv = reviewer.get(f"/api/reports/{rid}/export", params={"format": "csv"}).text
    assert "Deterministic check" in csv and "AI suggestion accepted" in csv


def test_cross_tenant_access_is_404(tenant_a: Tenant, tenant_b: Tenant, mock_ai: None) -> None:
    a = login(tenant_a.users[Role.REVIEWER])
    b = login(tenant_b.users[Role.REVIEWER])
    review = start_review(a, tenant_a)
    sug = _request(a, review["id"])["suggestions"][0]
    assert b.get(f"/api/reviews/{review['id']}/ai-suggestions").status_code == 404
    assert b.post(f"/api/reviews/{review['id']}/ai-suggestions").status_code == 404
    assert b.post(f"/api/ai-suggestions/{sug['id']}/accept", json={}).status_code == 404
    assert b.post(f"/api/ai-suggestions/{sug['id']}/reject", json={}).status_code == 404
    guessed = "00000000-0000-4000-8000-000000000000"
    assert a.post(f"/api/ai-suggestions/{guessed}/accept", json={}).status_code == 404


def test_prompt_keeps_document_text_fenced_and_within_budget(tenant_a: Tenant, db) -> None:  # type: ignore[no-untyped-def]
    client = login(tenant_a.users[Role.ANALYST])
    from tests.conftest import ready_version_id

    vid = ready_version_id(
        client, data=(FIXTURES / "ignore_instructions.txt").read_bytes(), filename="inject.txt"
    )
    blocks = list(
        db.scalars(
            select(SourceBlock)
            .where(SourceBlock.document_version_id == vid)
            .order_by(SourceBlock.ordinal)
        )
    )
    req = tenant_a.checklist_version.requirements[0]  # type: ignore[union-attr]
    chosen, left_out = ai_suggestions.select_blocks(blocks, req, budget=10_000)
    assert not left_out and [b.ordinal for b in chosen] == sorted(b.ordinal for b in chosen)
    prompt, labels = ai_suggestions.build_prompt(req, chosen)
    body = prompt.split("<<<DOCUMENT", 1)[1]
    assert "IGNORE ALL PREVIOUS INSTRUCTIONS" in body and body.rstrip().endswith("DOCUMENT>>>")
    assert "untrusted" in ai_suggestions.SYSTEM_PROMPT
    small, left_out = ai_suggestions.select_blocks(blocks, req, budget=60)
    assert left_out and sum(len(b.text) + 8 for b in small) <= 60
    assert ai_suggestions.parse_answer("no json here") is None
    assert ai_suggestions.parse_answer('{"assessment": "compliant"}') is None
