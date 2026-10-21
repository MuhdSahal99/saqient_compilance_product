"""Multi-agent AI tasks (Phase F4 assist, built out in Phase G).

Each task runs as a job: deterministic retrieval → specialist agent → deterministic
guards (citations, ids, numbers) → critic agent → stored draft. The draft is a
suggestion; a reviewer accepts or dismisses it. Accepting letter wording is the
only acceptance that changes other data (the letter point's recommendation).

Sending text to a model needs the deployment flag, a provider and the org admin's
opt-in, re-checked when the job runs. Nothing here logs prompts, answers or document
text; logs carry ids, counts and durations.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import ai
from app.ai.agents import definitions as d
from app.ai.agents.base import (
    Agent,
    AgentResult,
    StepRecord,
    fence,
    known_ids,
    run_agent,
    ungrounded_numbers,
)
from app.ai.citations import Citation, validate_citations
from app.config import Settings, get_settings
from app.models import (
    AITask,
    AITaskKind,
    AITaskStatus,
    AITaskStep,
    AuditEngagement,
    ChecklistState,
    ChecklistVersion,
    DocumentVersion,
    Finding,
    Job,
    JobKind,
    LetterPoint,
    Organization,
    Requirement,
    Rule,
    RulePackVersion,
    RuleVerification,
    Source,
    SourceBlock,
    SourceVerification,
    User,
    VersionStatus,
)
from app.services import audit
from app.services.ai_suggestions import _evidence_entry, feature_available
from app.services.engagements import EngagementError, require_open
from app.services.jobs import Checkpoint, PermanentJobError, handler, on_unsuccessful
from app.services.letters import REPORTABLE, evidence_refs, observation
from app.services.reports import _evidence_label

logger = logging.getLogger("saqient.ai_tasks")

AGENT_FEATURES = [k.value for k in AITaskKind]
MAX_QUESTION_CHARS = 1000
MAX_QA_ITEMS = 12
SUBJECTS = {
    AITaskKind.CONTRACT_TAX: "document_version",
    AITaskKind.FINDING_EXPLAIN: "finding",
    AITaskKind.LETTER_DRAFT: "letter_point",
    AITaskKind.PACK_QA: "organization",
}
AGENTS_FOR = {
    AITaskKind.CONTRACT_TAX: (d.CONTRACT_TAX, d.CRITIC),
    AITaskKind.FINDING_EXPLAIN: (d.FINDING_EXPLAINER, d.CRITIC),
    AITaskKind.LETTER_DRAFT: (d.LETTER_DRAFTER, d.CRITIC),
    AITaskKind.PACK_QA: (d.ROUTER, d.PACK_QA, d.CRITIC),
}
UNSUPPORTED_WARNING = (
    "The checking agent could not match part of this draft to the evidence; read it "
    "against the evidence before using it."
)


class AITaskError(Exception):
    """Business-rule violation; message is safe to show users."""


def _now() -> datetime:
    return datetime.now(UTC)


def org_enabled(org: Organization | None) -> bool:
    return bool(org is not None and org.ai_opt_in and feature_available())


def agent_catalogue(settings: Settings) -> list[dict[str, str]]:
    return [
        {
            "name": a.name,
            "tier": a.tier,
            "model": settings.ai_model_for(a.tier) or settings.ai_provider,
        }
        for a in d.ALL_AGENTS
    ]


# ---------------------------------------------------------------- request


def _subject_checks(db: Session, org_id: uuid.UUID, kind: AITaskKind, subject: Any) -> None:
    if kind is AITaskKind.CONTRACT_TAX:
        assert isinstance(subject, DocumentVersion)
        if subject.status != VersionStatus.READY or not subject.block_count:
            raise AITaskError("Wait until the document's text has been extracted.")
    elif kind is AITaskKind.LETTER_DRAFT:
        assert isinstance(subject, LetterPoint)
        if subject.finding.status not in REPORTABLE:
            raise AITaskError("Letter wording can only be drafted for confirmed findings.")
        engagement = db.get(AuditEngagement, subject.engagement_id)
        assert engagement is not None and engagement.org_id == org_id
        try:
            require_open(engagement)
        except EngagementError as exc:
            raise AITaskError(str(exc)) from exc


def request_task(
    db: Session,
    org: Organization,
    kind: AITaskKind,
    subject: Any,
    actor: User,
    question: str = "",
    language: str = "en",
) -> AITask:
    """Create a task and its job. ``subject`` was loaded through get_owned_or_404."""
    if not feature_available():
        raise AITaskError("AI is not enabled for this deployment.")
    if not org_enabled(org):
        raise AITaskError("An organisation admin has not turned on AI for this organisation.")
    if kind is AITaskKind.PACK_QA:
        question = " ".join(question.split())
        if not question:
            raise AITaskError("Type a question.")
        if len(question) > MAX_QUESTION_CHARS:
            raise AITaskError(f"Keep the question under {MAX_QUESTION_CHARS} characters.")
    _subject_checks(db, org.id, kind, subject)
    subject_id = org.id if kind is AITaskKind.PACK_QA else subject.id
    active = db.scalar(
        select(AITask.id).where(
            AITask.org_id == org.id,
            AITask.kind == kind,
            AITask.subject_id == subject_id,
            AITask.status == AITaskStatus.RUNNING,
            AITask.requested_by_id == actor.id,
        )
    )
    if active is not None:
        raise AITaskError("This AI task is already running.")
    s = get_settings()
    job = Job(org_id=org.id, kind=JobKind.AI_AGENT, target_id=uuid.uuid4(), max_attempts=2)
    db.add(job)
    db.flush()
    task = AITask(
        org_id=org.id,
        kind=kind,
        subject_type=SUBJECTS[kind],
        subject_id=subject_id,
        question=question,
        language=language if language in ("en", "ar") else "en",
        job_id=job.id,
        requested_by_id=actor.id,
        provider=s.ai_provider,
        prompt_version=d.PROMPT_VERSION,
        output={},
        warnings=[],
    )
    db.add(task)
    db.flush()
    job.target_id = task.id
    audit.record(
        db,
        org_id=org.id,
        actor_id=actor.id,
        action="ai.task_requested",
        object_type=SUBJECTS[kind],
        object_id=subject_id,
        meta={"task_id": str(task.id), "kind": kind.value, "provider": task.provider},
    )
    return task


# ---------------------------------------------------------------- pipeline


@dataclass
class _Run:
    settings: Settings
    steps: list[StepRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def call(self, agent: Agent[Any], prompt: str) -> AgentResult[Any]:
        result = run_agent(self.settings, agent, prompt)
        self.steps.append(result.step)
        return result

    def critic(self, claims: dict[str, str], evidence: str) -> set[str]:
        """Ask the critic; return the claim ids it found unsupported.

        A critic failure is a warning, not a task failure: the deterministic guards
        already ran and a person reviews every draft.
        """
        if not claims:
            return set()
        lines = [f"[{cid}] {' '.join(text.split())}" for cid, text in claims.items()]
        prompt = "\n".join([fence("CLAIMS", "\n".join(lines)), "", fence("EVIDENCE", evidence)])
        result = self.call(d.CRITIC, prompt)
        if result.value is None:
            self.warnings.append("The checking agent did not answer; this draft is unchecked.")
            return set()
        verdicts = {v.claim: v.supported for v in result.value.verdicts}
        return {cid for cid in claims if verdicts.get(cid) is False}


def _require(result: AgentResult[Any], what: str) -> Any:
    if result.value is None:
        if result.step.status == "provider_error":
            raise RuntimeError("AI provider unavailable")  # let the job retry
        raise PermanentJobError(f"The model's answer for the {what} could not be read.")
    return result.value


def _blocks(db: Session, version: DocumentVersion, budget: int) -> tuple[list[SourceBlock], bool]:
    blocks = list(
        db.scalars(
            select(SourceBlock)
            .where(
                SourceBlock.document_version_id == version.id,
                SourceBlock.org_id == version.org_id,
            )
            .order_by(SourceBlock.ordinal)
        )
    )
    chosen, used = [], 0
    for b in blocks:
        cost = len(b.text) + 8
        if used + cost > budget:
            break
        chosen.append(b)
        used += cost
    return chosen, len(chosen) < len(blocks)


def _contract(db: Session, task: AITask, run: _Run) -> dict[str, Any]:
    version = db.scalar(
        select(DocumentVersion).where(
            DocumentVersion.id == task.subject_id, DocumentVersion.org_id == task.org_id
        )
    )
    if version is None:
        raise PermanentJobError("The document version no longer exists.")
    budget = max(1000, run.settings.ai_max_input_chars - len(d.CONTRACT_TAX.system) - 500)
    blocks, truncated = _blocks(db, version, budget)
    if truncated:
        run.warnings.append(
            "Only the first part of the document fitted in the AI input; later text was not read."
        )
    labels = {f"B{i + 1}": b for i, b in enumerate(blocks)}
    lines = [f"[{label}] {' '.join(b.text.split())}" for label, b in labels.items()]
    answer: d.ContractAnswer = _require(
        run.call(d.CONTRACT_TAX, fence("DOCUMENT", "\n".join(lines))), "contract scan"
    )
    items: list[dict[str, Any]] = []
    rejected = 0
    allowed_cues = set(d.VAT_CUES) | set(d.RELATED_PARTY_CUES)
    for item in answer.items:
        cites = [
            Citation(str(labels[c.block].id) if c.block in labels else c.block, c.quote)
            for c in item.citations
        ]
        results = validate_citations(db, task.org_id, cites, {version.id})
        by_id = {str(b.id): b for b in labels.values()}
        evidence = [
            _evidence_entry(by_id[r.block_id], r.quote) for r in results if r.status == "valid"
        ]
        rejected += sum(1 for r in results if r.status != "valid")
        if not evidence or item.cue not in allowed_cues:
            continue  # no verifiable quote, no suggestion
        items.append(
            {
                "topic": item.topic,
                "cue": item.cue,
                "summary": " ".join(item.summary.split()),
                "question_for_reviewer": " ".join(item.question_for_reviewer.split()),
                "evidence": evidence[:3],
                "checked": True,
            }
        )
    if rejected:
        run.warnings.append(
            f"{rejected} quoted passage(s) did not match the document and were removed."
        )
    claims = {f"C{i + 1}": it["summary"] for i, it in enumerate(items)}
    evidence_text = "\n".join(
        f"[C{i + 1}] " + " | ".join(e["quote"] for e in it["evidence"])
        for i, it in enumerate(items)
    )
    for cid in run.critic(claims, evidence_text):
        items[int(cid[1:]) - 1]["checked"] = False
    if any(not it["checked"] for it in items):
        run.warnings.append(UNSUPPORTED_WARNING)
    return {"document_version_id": str(version.id), "items": items}


def _finding_evidence(f: Finding) -> tuple[str, list[str]]:
    lines, ids = [], []
    for i, e in enumerate((f.evidence or [])[:12]):
        eid = f"E{i + 1}"
        ids.append(eid)
        values = {
            k: v
            for k, v in e.items()
            if k not in ("block_id", "dataset_version_id", "file_id", "sha256", "row_ids")
            and isinstance(v, str | int | float | dict | list)
        }
        detail = json.dumps(values, ensure_ascii=False, default=str)[:1200]
        lines.append(f"[{eid}] {_evidence_label(e)} :: {detail}")
    return "\n".join(lines), ids


def _finding_text(f: Finding) -> str:
    req = f.requirement
    return "\n".join(
        [
            f"Title: {f.title}",
            f"Severity: {f.severity.value}",
            f"Status: {f.status.value}",
            f"Check: {req.title if req else 'manual finding'}",
            f"Description: {f.description}",
        ]
    )


def _explain(db: Session, task: AITask, run: _Run) -> dict[str, Any]:
    f = db.scalar(
        select(Finding).where(Finding.id == task.subject_id, Finding.org_id == task.org_id)
    )
    if f is None:
        raise PermanentJobError("The finding no longer exists.")
    evidence, ids = _finding_evidence(f)
    source = _finding_text(f) + "\n" + evidence
    prompt = "\n".join([fence("FINDING", _finding_text(f)), "", fence("EVIDENCE", evidence)])
    answer: d.ExplainAnswer = _require(run.call(d.FINDING_EXPLAINER, prompt), "explanation")
    used, dropped = known_ids(answer.evidence_used, set(ids))
    if dropped:
        run.warnings.append(f"{dropped} evidence reference(s) did not exist and were removed.")
    draft = " ".join([answer.explanation_en, *answer.next_steps_en])
    stray = ungrounded_numbers(draft + " " + answer.explanation_ar, source)
    if stray:
        run.warnings.append(
            "The draft mentions numbers that are not in the finding or its evidence: "
            + ", ".join(stray[:5])
        )
    unsupported = run.critic(
        {"C1": answer.explanation_en, "C2": " ".join(answer.next_steps_en)}, source
    )
    if unsupported:
        run.warnings.append(UNSUPPORTED_WARNING)
    return {
        "finding_id": str(f.id),
        "explanation_en": answer.explanation_en.strip(),
        "explanation_ar": answer.explanation_ar.strip(),
        "next_steps_en": [s.strip() for s in answer.next_steps_en if s.strip()],
        "next_steps_ar": [s.strip() for s in answer.next_steps_ar if s.strip()],
        "evidence_used": used,
        "checked": not unsupported and not stray,
    }


def _letter(db: Session, task: AITask, run: _Run) -> dict[str, Any]:
    p = db.scalar(
        select(LetterPoint).where(
            LetterPoint.id == task.subject_id, LetterPoint.org_id == task.org_id
        )
    )
    if p is None:
        raise PermanentJobError("The letter point no longer exists.")
    f = p.finding
    if f.status not in REPORTABLE:
        raise PermanentJobError("The finding is no longer confirmed.")
    source = "\n".join(
        [
            _finding_text(f),
            "Observation: " + observation(f),
            "Evidence: " + "; ".join(evidence_refs(f)),
        ]
    )
    lang = "Arabic (Modern Standard)" if task.language == "ar" else "English"
    prompt = f"Write in: {lang}\n\n" + fence("FINDING", source)
    answer: d.LetterAnswer = _require(run.call(d.LETTER_DRAFTER, prompt), "letter wording")
    stray = ungrounded_numbers(answer.implication + " " + answer.recommendation, source)
    if stray:
        run.warnings.append(
            "The draft mentions numbers that are not in the finding: " + ", ".join(stray[:5])
        )
    unsupported = run.critic({"C1": answer.implication, "C2": answer.recommendation}, source)
    if unsupported:
        run.warnings.append(UNSUPPORTED_WARNING)
    return {
        "letter_point_id": str(p.id),
        "finding_id": str(f.id),
        "implication": answer.implication.strip(),
        "recommendation": answer.recommendation.strip(),
        "checked": not unsupported and not stray,
    }


_TERM = re.compile(r"\w{3,}", re.UNICODE)


def _terms(text: str) -> set[str]:
    return {w.casefold() for w in _TERM.findall(text)}


def verified_content(db: Session, org_id: uuid.UUID) -> list[tuple[str, str, dict[str, Any]]]:
    """Verified rules in published packs and requirements with a verified source.

    Returns (kind, text, reference) tuples. Draft rules and unverified sources are
    never offered to the model.
    """
    out: list[tuple[str, str, dict[str, Any]]] = []
    rules = db.scalars(
        select(Rule)
        .join(RulePackVersion, RulePackVersion.id == Rule.rule_pack_version_id)
        .where(
            Rule.org_id == org_id,
            Rule.verification_status == RuleVerification.VERIFIED,
            RulePackVersion.state == ChecklistState.PUBLISHED,
        )
    )
    for r in rules:
        text = (
            f"{r.title} ({r.rule_key}) = {r.value} {r.unit}; effective {r.effective_from}"
            f"{' to ' + str(r.effective_to) if r.effective_to else ''}; "
            f"pack {r.version.rule_pack.name} v{r.version.version_number}; "
            f"source {r.source_url or ''}"
        )
        out.append(
            ("rule", text, {"type": "rule", "id": str(r.id), "key": r.rule_key, "title": r.title})
        )
    reqs = db.scalars(
        select(Requirement)
        .join(ChecklistVersion, ChecklistVersion.id == Requirement.checklist_version_id)
        .join(Source, Source.id == Requirement.source_id)
        .where(
            Requirement.org_id == org_id,
            ChecklistVersion.state == ChecklistState.PUBLISHED,
            Source.verification_status == SourceVerification.VERIFIED,
        )
    )
    for q in reqs:
        text = (
            f"{q.code} {q.title}: {q.description} (source: {q.source.title if q.source else ''}"
            f" {q.source_reference})"
        )
        out.append(
            (
                "requirement",
                text,
                {"type": "requirement", "id": str(q.id), "key": q.code, "title": q.title},
            )
        )
    return out


def _qa(db: Session, task: AITask, run: _Run) -> dict[str, Any]:
    routed = run.call(d.ROUTER, fence("QUESTION", task.question))
    language = task.language
    terms = _terms(task.question)
    if routed.value is not None:
        language = routed.value.language
        terms |= _terms(" ".join(routed.value.search_terms))
    else:
        run.warnings.append("The routing agent did not answer; searched with the question's words.")
    content = verified_content(db, task.org_id)
    ranked = sorted(
        ((len(terms & _terms(text)), kind, text, ref) for kind, text, ref in content),
        key=lambda x: -x[0],
    )
    chosen = [r for r in ranked if r[0] > 0][:MAX_QA_ITEMS]
    base = {"question": task.question, "language": language}
    if not chosen:
        return base | {
            "answer": "",
            "insufficient": True,
            "sources": [],
            "checked": True,
            "note": "No verified rule or requirement matches this question.",
        }
    labels: dict[str, tuple[str, dict[str, Any]]] = {}
    counts = {"rule": 0, "requirement": 0}
    for _, kind, text, ref in chosen:
        counts[kind] += 1
        label = f"{'R' if kind == 'rule' else 'Q'}{counts[kind]}"
        labels[label] = (text, ref)
    items = "\n".join(f"[{label}] {text}" for label, (text, _) in labels.items())
    lang = "Arabic (Modern Standard)" if language == "ar" else "English"
    prompt = "\n".join(
        [f"Answer in: {lang}", "", fence("QUESTION", task.question), "", fence("ITEMS", items)]
    )
    answer: d.QAAnswer = _require(run.call(d.PACK_QA, prompt), "answer")
    cited, dropped = known_ids(answer.citations, set(labels))
    if dropped:
        run.warnings.append(f"{dropped} citation(s) to items that were not supplied were removed.")
    insufficient = answer.insufficient or not cited
    stray = ungrounded_numbers(answer.answer, items + " " + task.question)
    if stray:
        run.warnings.append(
            "The answer mentions numbers that are not in the verified content: "
            + ", ".join(stray[:5])
        )
    unsupported: set[str] = set()
    if not insufficient:
        unsupported = run.critic(
            {"C1": answer.answer}, "\n".join(f"[{c}] {labels[c][0]}" for c in cited)
        )
        if unsupported:
            run.warnings.append(UNSUPPORTED_WARNING)
    return base | {
        "answer": answer.answer.strip(),
        "insufficient": insufficient,
        "sources": [labels[c][1] | {"label": c} for c in cited],
        "checked": not unsupported and not stray,
    }


PIPELINES = {
    AITaskKind.CONTRACT_TAX: _contract,
    AITaskKind.FINDING_EXPLAIN: _explain,
    AITaskKind.LETTER_DRAFT: _letter,
    AITaskKind.PACK_QA: _qa,
}


@handler(JobKind.AI_AGENT)
def execute_task(db: Session, job: Job, checkpoint: Checkpoint) -> None:
    task = db.scalar(select(AITask).where(AITask.id == job.target_id, AITask.org_id == job.org_id))
    if task is None:
        raise PermanentJobError("The AI request no longer exists.")
    s = get_settings()
    try:
        provider = ai.get_provider(s)
    except Exception as exc:
        raise PermanentJobError("AI is not configured correctly for this deployment.") from exc
    if provider.name == "disabled" or provider.name != task.provider:
        raise PermanentJobError("The AI provider changed or was disabled; request again.")
    if not org_enabled(db.get(Organization, job.org_id)):
        raise PermanentJobError("AI was turned off for this organisation.")
    checkpoint(5)
    run = _Run(s)
    try:
        output = PIPELINES[task.kind](db, task, run)
    finally:
        # Keep a record of every agent call, including on a failed attempt.
        start = len(task.steps)
        for i, st in enumerate(run.steps):
            task.steps.append(
                AITaskStep(
                    org_id=task.org_id,
                    ordinal=start + i,
                    agent=st.agent,
                    tier=st.tier,
                    provider=st.provider,
                    model=st.model[:200],
                    model_version=st.model_version[:200],
                    status=st.status,
                    duration_ms=st.duration_ms,
                    input_tokens=st.input_tokens,
                    output_tokens=st.output_tokens,
                    note=st.note[:300],
                )
            )
        db.commit()
    if task.provider == "mock":
        run.warnings.insert(0, "Mock provider output: a placeholder for testing, not analysis.")
    task.output = output
    task.warnings = run.warnings
    task.status = AITaskStatus.READY
    task.finished_at = _now()
    logger.info(
        "ai task completed",
        extra={
            "task_id": str(task.id),
            "kind": task.kind.value,
            "steps": len(run.steps),
            "warnings": len(run.warnings),
        },
    )
    db.commit()


@on_unsuccessful(JobKind.AI_AGENT)
def _mark_failed(db: Session, job: Job) -> None:
    task = db.scalar(select(AITask).where(AITask.id == job.target_id, AITask.org_id == job.org_id))
    if task is not None and task.status == AITaskStatus.RUNNING:
        task.status = AITaskStatus.FAILED
        task.error = job.error or "The AI task failed."
        task.finished_at = _now()


# ---------------------------------------------------------------- decisions


def _check_ready(task: AITask) -> None:
    if task.status != AITaskStatus.READY:
        raise AITaskError(
            "Only a finished draft that has not been decided can be accepted or dismissed."
        )


def accept(db: Session, task: AITask, actor: User, note: str) -> None:
    _check_ready(task)
    if task.kind is AITaskKind.PACK_QA and task.output.get("insufficient"):
        raise AITaskError("There is no answer to accept; dismiss it instead.")
    meta: dict[str, Any] = {"task_id": str(task.id), "kind": task.kind.value}
    if task.kind is AITaskKind.LETTER_DRAFT:
        p = db.scalar(
            select(LetterPoint).where(
                LetterPoint.id == task.subject_id, LetterPoint.org_id == task.org_id
            )
        )
        if p is None:
            raise AITaskError("The letter point no longer exists.")
        engagement = db.get(AuditEngagement, p.engagement_id)
        assert engagement is not None
        try:
            require_open(engagement)
        except EngagementError as exc:
            raise AITaskError(str(exc)) from exc
        if p.finding.status not in REPORTABLE:
            raise AITaskError("The finding is no longer confirmed.")
        p.recommendation = str(task.output.get("recommendation", "")).strip()
        meta["letter_point_id"] = str(p.id)
    task.status = AITaskStatus.ACCEPTED
    task.decided_by_id = actor.id
    task.decided_at = _now()
    task.decision_note = note.strip()[:2000]
    meta["models"] = sorted({s.model for s in task.steps})
    audit.record(
        db,
        org_id=task.org_id,
        actor_id=actor.id,
        action="ai.task_accepted",
        object_type=task.subject_type,
        object_id=task.subject_id,
        meta=meta,
    )


def dismiss(db: Session, task: AITask, actor: User, note: str) -> None:
    _check_ready(task)
    task.status = AITaskStatus.DISMISSED
    task.decided_by_id = actor.id
    task.decided_at = _now()
    task.decision_note = note.strip()[:2000]
    audit.record(
        db,
        org_id=task.org_id,
        actor_id=actor.id,
        action="ai.task_dismissed",
        object_type=task.subject_type,
        object_id=task.subject_id,
        meta={"task_id": str(task.id), "kind": task.kind.value},
    )
