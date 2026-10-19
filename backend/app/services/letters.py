"""Management letter from confirmed findings of the engagement's reviews (D8).

Points are drawn only from findings a reviewer has confirmed (or later moved into
remediation, resolved or accepted as a risk); proposed and dismissed findings never
appear. The team writes each recommendation and records management's response; an
issued letter is an immutable, versioned snapshot.
"""

from __future__ import annotations

from typing import Any
from xml.sax.saxutils import escape

from jinja2 import Environment, select_autoescape
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.deps import now
from app.models import (
    AuditEngagement,
    Finding,
    FindingStatus,
    LetterPoint,
    LetterSnapshot,
    Review,
    Severity,
    User,
)
from app.schemas import LetterPointIn
from app.services import audit
from app.services.engagements import EngagementError, require_open
from app.services.reports import _evidence_label

REPORTABLE = (
    FindingStatus.CONFIRMED,
    FindingStatus.REMEDIATION_IN_PROGRESS,
    FindingStatus.READY_FOR_REREVIEW,
    FindingStatus.RESOLVED,
    FindingStatus.ACCEPTED_RISK,
)
SEVERITY_ORDER = {
    s: i for i, s in enumerate([Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW])
}
DISCLAIMER = (
    "This letter reports matters that came to our attention during the engagement. It is "
    "not a complete statement of all weaknesses that may exist, and it is not an audit "
    "opinion or a certification of compliance."
)
SYNTHETIC = "Contains synthetic demonstration content — not legal guidance."


def observation(f: Finding) -> str:
    parts = [f.description.strip(), f.decision_rationale.strip()]
    return "\n\n".join(p for p in parts if p)


def evidence_refs(f: Finding) -> list[str]:
    return [_evidence_label(e) for e in (f.evidence or [])][:10]


def points(db: Session, e: AuditEngagement) -> list[LetterPoint]:
    return list(
        db.scalars(
            select(LetterPoint)
            .where(LetterPoint.org_id == e.org_id, LetterPoint.engagement_id == e.id)
            .order_by(LetterPoint.ordinal)
        ).unique()
    )


def refresh(db: Session, e: AuditEngagement, actor: User) -> list[LetterPoint]:
    """Add a point for every reportable finding not yet on the letter."""
    require_open(e)
    have = {p.finding_id for p in points(db, e)}
    found = db.scalars(
        select(Finding)
        .join(Review, Review.id == Finding.review_id)
        .where(
            Finding.org_id == e.org_id,
            Review.engagement_id == e.id,
            Finding.status.in_(REPORTABLE),
        )
    ).unique()
    new = sorted(
        (f for f in found if f.id not in have),
        key=lambda f: (SEVERITY_ORDER[f.severity], f.created_at),
    )
    start = len(have)
    for i, f in enumerate(new):
        db.add(LetterPoint(org_id=e.org_id, engagement_id=e.id, finding_id=f.id, ordinal=start + i))
    db.flush()
    audit.record(
        db,
        org_id=e.org_id,
        actor_id=actor.id,
        action="letter.refreshed",
        object_type="audit_engagement",
        object_id=e.id,
        meta={"added": len(new)},
    )
    return points(db, e)


def update_point(
    db: Session, e: AuditEngagement, p: LetterPoint, body: LetterPointIn, actor: User
) -> None:
    require_open(e)
    p.include = body.include
    p.recommendation = body.recommendation.strip()
    p.management_response = body.management_response.strip()
    p.response_owner = body.response_owner.strip()
    p.response_due = body.response_due
    db.flush()
    audit.record(
        db,
        org_id=e.org_id,
        actor_id=actor.id,
        action="letter.point_updated",
        object_type="letter_point",
        object_id=p.id,
        meta={"include": p.include},
    )


def snapshots(db: Session, e: AuditEngagement) -> list[LetterSnapshot]:
    return list(
        db.scalars(
            select(LetterSnapshot)
            .where(LetterSnapshot.org_id == e.org_id, LetterSnapshot.engagement_id == e.id)
            .order_by(LetterSnapshot.version)
        )
    )


def issue(db: Session, e: AuditEngagement, actor: User) -> LetterSnapshot:
    included = [p for p in points(db, e) if p.include]
    if not included:
        raise EngagementError("There are no points to include in the letter.")
    for p in included:
        if p.finding.status not in REPORTABLE:
            raise EngagementError(f"'{p.finding.title}' is no longer a confirmed finding.")
        if not p.recommendation:
            raise EngagementError(f"Write a recommendation for '{p.finding.title}'.")
    version = (
        db.scalar(
            select(func.max(LetterSnapshot.version)).where(LetterSnapshot.engagement_id == e.id)
        )
        or 0
    ) + 1
    at = now()
    content: dict[str, Any] = {
        "version": version,
        "engagement": {
            "id": str(e.id),
            "name": e.name,
            "kind": e.kind.value,
            "period_start": e.period_start.isoformat(),
            "period_end": e.period_end.isoformat(),
        },
        "entity": {"id": str(e.entity_id), "name": e.entity.name},
        "is_demo": e.is_demo,
        "issued_by": actor.full_name,
        "issued_at": at.isoformat(),
        "points": [
            {
                "number": i + 1,
                "finding_id": str(p.finding_id),
                "review_id": str(p.finding.review_id),
                "title": p.finding.title,
                "severity": p.finding.severity.value,
                "status": p.finding.status.value,
                "observation": observation(p.finding),
                "evidence": evidence_refs(p.finding),
                "recommendation": p.recommendation,
                "management_response": p.management_response,
                "response_owner": p.response_owner,
                "response_due": p.response_due.isoformat() if p.response_due else None,
            }
            for i, p in enumerate(included)
        ],
    }
    snap = LetterSnapshot(
        org_id=e.org_id,
        engagement_id=e.id,
        version=version,
        content=content,
        issued_by_id=actor.id,
        issued_at=at,
    )
    db.add(snap)
    db.flush()
    audit.record(
        db,
        org_id=e.org_id,
        actor_id=actor.id,
        action="letter.issued",
        object_type="audit_engagement",
        object_id=e.id,
        meta={"version": version, "points": len(included)},
    )
    return snap


_env = Environment(autoescape=select_autoescape(default=True))
HTML = _env.from_string(
    """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Management letter — {{ c.engagement.name }} (v{{ c.version }})</title>
<style>
body{font-family:system-ui,-apple-system,"Segoe UI",Tahoma,sans-serif;color:#0f172a;margin:2rem auto;max-width:860px;padding:0 1rem;line-height:1.55}
h1{color:#14284b;font-size:1.5rem;margin-bottom:.25rem}h2{color:#14284b;font-size:1.1rem;border-bottom:2px solid #0f766e;padding-bottom:.25rem;margin-top:2rem}
.muted{color:#475569}.synthetic{background:#fef3c7;border:1px solid #f59e0b;padding:.5rem .75rem;border-radius:6px}
.disclaimer{background:#f8fafc;border-inline-start:4px solid #0f766e;padding:.75rem 1rem}
dt{font-weight:600;margin-top:.5rem}dd{margin-inline-start:0;white-space:pre-line}
@media print{body{margin:0}}
</style></head><body>
<p class="muted">Saqient Compliance Workspace · Management letter version {{ c.version }} · issued {{ c.issued_at[:10] }} by {{ c.issued_by }}</p>
<h1>{{ c.engagement.name }}</h1>
<p>{{ c.entity.name }} · {{ c.engagement.period_start }} to {{ c.engagement.period_end }}</p>
{% if c.is_demo %}<p class="synthetic">{{ synthetic }}</p>{% endif %}
<p class="disclaimer">{{ disclaimer }}</p>
{% for p in c.points %}
<h2>{{ p.number }}. {{ p.title }} <span class="muted">({{ p.severity }})</span></h2>
<dl>
<dt>Observation</dt><dd>{{ p.observation or "—" }}</dd>
{% if p.evidence %}<dt>Evidence</dt><dd>{% for ev in p.evidence %}{{ ev }}
{% endfor %}</dd>{% endif %}
<dt>Recommendation</dt><dd>{{ p.recommendation }}</dd>
<dt>Management response</dt><dd>{{ p.management_response or "Awaiting response" }}{% if p.response_owner %} — {{ p.response_owner }}{% endif %}{% if p.response_due %}, by {{ p.response_due }}{% endif %}</dd>
</dl>
{% endfor %}
</body></html>"""
)


def render_html(c: dict[str, Any]) -> str:
    return HTML.render(c=c, disclaimer=DISCLAIMER, synthetic=SYNTHETIC)


def render_pdf(c: dict[str, Any]) -> bytes:
    import io

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    styles = getSampleStyleSheet()
    navy = colors.HexColor("#14284b")
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], textColor=navy, fontSize=15)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], textColor=navy, fontSize=11)
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=9, leading=12)

    def p(text: Any, style: ParagraphStyle = body) -> Paragraph:
        return Paragraph(escape("" if text is None else str(text)).replace("\n", "<br/>"), style)

    story: list[Any] = [
        p(f"Saqient Compliance Workspace · Management letter version {c['version']}"),
        p(c["engagement"]["name"], h1),
        p(
            f"{c['entity']['name']} · {c['engagement']['period_start']} to {c['engagement']['period_end']}"
        ),
    ]
    if c.get("is_demo"):
        story.append(p(SYNTHETIC))
    story += [Spacer(1, 6), p(DISCLAIMER)]
    for pt in c["points"]:
        story += [
            p(f"{pt['number']}. {pt['title']} ({pt['severity']})", h2),
            p(f"Observation: {pt['observation'] or '—'}"),
        ]
        if pt["evidence"]:
            story.append(p("Evidence: " + "; ".join(pt["evidence"])))
        story += [
            p(f"Recommendation: {pt['recommendation']}"),
            p(f"Management response: {pt['management_response'] or 'Awaiting response'}"),
        ]
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, title=c["engagement"]["name"]).build(story)
    return buf.getvalue()
