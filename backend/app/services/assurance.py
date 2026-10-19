"""Shared sign-off and export for Phase E objects.

Reconciliations, flux reviews and certifications use one flow: the preparer marks the
object prepared, a reviewer or admin who is not the preparer signs it off, and sign-off
freezes an immutable snapshot (version n). Reopening needs a reason; the next sign-off
is version n+1. Exports render only from a snapshot.

Snapshot content shape: ``title``, ``subtitle``, ``meta`` ([label, value] pairs),
``warnings``, ``sections`` ([{title, columns, rows}]), ``notes``, plus who prepared and
signed it.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import uuid
from typing import Any
from xml.sax.saxutils import escape

from jinja2 import Environment, select_autoescape
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.deps import now
from app.models import (
    AssuranceObject,
    AssuranceSnapshot,
    AssuranceStatus,
    SignOffMixin,
    User,
)
from app.services import audit
from app.services.reports import csv_safe

DISCLAIMER = (
    "Prepared from the data and evidence recorded in Saqient. It supports, and does not "
    "replace, the judgement of the people who prepared and signed it off. It is not an "
    "audit opinion or a certification of compliance."
)
SYNTHETIC = "Contains synthetic demonstration content — not legal guidance."


class AssuranceError(ValueError):
    pass


class AssuranceConflict(AssuranceError):
    pass


def require_draft(obj: SignOffMixin) -> None:
    if obj.status is AssuranceStatus.SIGNED_OFF:
        raise AssuranceConflict("It is signed off. Reopen it with a reason first.")


def _touch(obj: SignOffMixin) -> None:
    """Any change after preparing sends the object back to draft."""
    if obj.status is AssuranceStatus.PREPARED:
        obj.status = AssuranceStatus.DRAFT
        obj.prepared_by_id = obj.prepared_at = None


def changed(obj: SignOffMixin) -> None:
    require_draft(obj)
    _touch(obj)


def _record(
    db: Session, obj: Any, kind: AssuranceObject, actor: User, action: str, **meta: Any
) -> None:
    audit.record(
        db,
        org_id=obj.org_id,
        actor_id=actor.id,
        action=f"{kind.value}.{action}",
        object_type=kind.value,
        object_id=obj.id,
        meta=meta,
    )


def prepare(db: Session, obj: Any, kind: AssuranceObject, actor: User) -> None:
    require_draft(obj)
    if obj.status is AssuranceStatus.PREPARED:
        raise AssuranceConflict("It is already marked prepared.")
    obj.status, obj.prepared_by_id, obj.prepared_at = AssuranceStatus.PREPARED, actor.id, now()
    db.flush()
    _record(db, obj, kind, actor, "prepared")


def digest(content: dict[str, Any]) -> str:
    raw = json.dumps(content, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def sign_off(
    db: Session, obj: Any, kind: AssuranceObject, content: dict[str, Any], actor: User
) -> AssuranceSnapshot:
    if obj.status is not AssuranceStatus.PREPARED:
        raise AssuranceConflict("Mark it prepared before signing off.")
    if obj.prepared_by_id == actor.id:
        raise AssuranceError("The reviewer who signs off must not be the preparer.")
    version = (
        db.scalar(
            select(func.max(AssuranceSnapshot.version)).where(
                AssuranceSnapshot.object_type == kind, AssuranceSnapshot.object_id == obj.id
            )
        )
        or 0
    ) + 1
    at = now()
    preparer = db.get(User, obj.prepared_by_id) if obj.prepared_by_id else None
    content = {
        **content,
        "object_type": kind.value,
        "version": version,
        "prepared_by": preparer.full_name if preparer else None,
        "prepared_at": obj.prepared_at.isoformat() if obj.prepared_at else None,
        "signed_by": actor.full_name,
        "signed_at": at.isoformat(),
    }
    content = json.loads(json.dumps(content, default=str))
    snap = AssuranceSnapshot(
        org_id=obj.org_id,
        object_type=kind,
        object_id=obj.id,
        version=version,
        content=content,
        sha256=digest(content),
        signed_by_id=actor.id,
        signed_at=at,
    )
    db.add(snap)
    obj.status, obj.signed_off_by_id, obj.signed_off_at = AssuranceStatus.SIGNED_OFF, actor.id, at
    obj.version = version
    db.flush()
    _record(db, obj, kind, actor, "signed_off", version=version, sha256=snap.sha256)
    return snap


def reopen(db: Session, obj: Any, kind: AssuranceObject, reason: str, actor: User) -> None:
    if obj.status is not AssuranceStatus.SIGNED_OFF:
        raise AssuranceConflict("Only a signed-off item can be reopened.")
    if not reason.strip():
        raise AssuranceError("Give a reason for reopening.")
    obj.status = AssuranceStatus.DRAFT
    obj.prepared_by_id = obj.prepared_at = None
    obj.signed_off_by_id = obj.signed_off_at = None
    obj.reopen_reason = reason.strip()
    db.flush()
    _record(db, obj, kind, actor, "reopened", reason=reason.strip())


def snapshots(
    db: Session, org_id: uuid.UUID, kind: AssuranceObject, object_id: uuid.UUID
) -> list[AssuranceSnapshot]:
    return list(
        db.scalars(
            select(AssuranceSnapshot)
            .where(
                AssuranceSnapshot.org_id == org_id,
                AssuranceSnapshot.object_type == kind,
                AssuranceSnapshot.object_id == object_id,
            )
            .order_by(AssuranceSnapshot.version)
        )
    )


def snapshot(
    db: Session, org_id: uuid.UUID, kind: AssuranceObject, object_id: uuid.UUID, version: int
) -> AssuranceSnapshot | None:
    return db.scalar(
        select(AssuranceSnapshot).where(
            AssuranceSnapshot.org_id == org_id,
            AssuranceSnapshot.object_type == kind,
            AssuranceSnapshot.object_id == object_id,
            AssuranceSnapshot.version == version,
        )
    )


# ---------------------------------------------------------------- exports

_env = Environment(autoescape=select_autoescape(default=True))
HTML = _env.from_string(
    """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>{{ c.title }} (v{{ c.version }})</title>
<style>
body{font-family:system-ui,-apple-system,"Segoe UI",Tahoma,sans-serif;color:#0f172a;margin:2rem auto;max-width:1000px;padding:0 1rem;line-height:1.5}
h1{color:#14284b;font-size:1.4rem;margin-bottom:.25rem}h2{color:#14284b;font-size:1.05rem;border-bottom:2px solid #0f766e;padding-bottom:.25rem;margin-top:1.75rem}
.muted{color:#475569}.warn{background:#fef3c7;border:1px solid #f59e0b;padding:.5rem .75rem;border-radius:6px}
.disclaimer{background:#f8fafc;border-inline-start:4px solid #0f766e;padding:.75rem 1rem}
table{border-collapse:collapse;width:100%;font-size:.85rem}th,td{border:1px solid #cbd5e1;padding:.3rem .5rem;text-align:start;vertical-align:top}th{background:#f1f5f9}
@media print{body{margin:0}}
</style></head><body>
<p class="muted">Saqient Compliance Workspace · version {{ c.version }} · prepared by {{ c.prepared_by or "—" }} · signed off {{ (c.signed_at or "")[:10] }} by {{ c.signed_by }}</p>
<h1>{{ c.title }}</h1>
{% if c.subtitle %}<p>{{ c.subtitle }}</p>{% endif %}
{% if c.is_demo %}<p class="warn">{{ synthetic }}</p>{% endif %}
{% for w in c.warnings %}<p class="warn">{{ w }}</p>{% endfor %}
<p class="disclaimer">{{ disclaimer }}</p>
<table>{% for k, v in c.meta %}<tr><th>{{ k }}</th><td>{{ v if v is not none else "—" }}</td></tr>{% endfor %}</table>
{% for s in c.sections %}
<h2>{{ s.title }}</h2>
{% if s.rows %}<table><tr>{% for col in s.columns %}<th>{{ col }}</th>{% endfor %}</tr>
{% for r in s.rows %}<tr>{% for v in r %}<td>{{ v if v is not none else "—" }}</td>{% endfor %}</tr>{% endfor %}</table>
{% else %}<p class="muted">None.</p>{% endif %}
{% endfor %}
{% for n in c.notes %}<p>{{ n }}</p>{% endfor %}
</body></html>"""
)


def render_html(c: dict[str, Any]) -> str:
    return HTML.render(c=c, disclaimer=DISCLAIMER, synthetic=SYNTHETIC)


def render_csv(c: dict[str, Any]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([csv_safe(c["title"]), f"version {c['version']}"])
    for k, v in c.get("meta", []):
        w.writerow([csv_safe(k), csv_safe(v)])
    for warning in c.get("warnings", []):
        w.writerow(["warning", csv_safe(warning)])
    for s in c.get("sections", []):
        w.writerow([])
        w.writerow([csv_safe(s["title"])])
        w.writerow([csv_safe(x) for x in s["columns"]])
        for r in s["rows"]:
            w.writerow([csv_safe(x) for x in r])
    return buf.getvalue()


def render_pdf(c: dict[str, Any]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    navy = colors.HexColor("#14284b")
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], textColor=navy, fontSize=14)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], textColor=navy, fontSize=11)
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=8, leading=10)

    def p(text: Any, style: ParagraphStyle = body) -> Paragraph:
        return Paragraph(escape("—" if text is None else str(text)), style)

    def table(rows: list[list[Any]]) -> Table:
        t = Table([[p(v) for v in r] for r in rows], repeatRows=1)
        t.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        return t

    story: list[Any] = [
        p(
            f"Saqient Compliance Workspace · version {c['version']} · signed off by "
            f"{c.get('signed_by')} on {(c.get('signed_at') or '')[:10]}"
        ),
        p(c["title"], h1),
    ]
    if c.get("subtitle"):
        story.append(p(c["subtitle"]))
    if c.get("is_demo"):
        story.append(p(SYNTHETIC))
    story += [p(w) for w in c.get("warnings", [])]
    story += [Spacer(1, 4), p(DISCLAIMER), Spacer(1, 6)]
    if c.get("meta"):
        story.append(table([["Item", "Value"], *[[k, v] for k, v in c["meta"]]]))
    for s in c.get("sections", []):
        story.append(p(s["title"], h2))
        story.append(table([s["columns"], *s["rows"]]) if s["rows"] else p("None."))
    story += [p(n) for n in c.get("notes", [])]
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=landscape(A4), title=c["title"]).build(story)
    return buf.getvalue()
