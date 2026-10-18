"""Report renderers. They read only from an immutable ReportSnapshot."""

from __future__ import annotations

import csv
import io
from typing import Any
from xml.sax.saxutils import escape

from jinja2 import Environment, select_autoescape

_env = Environment(autoescape=select_autoescape(default=True, default_for_string=True))

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value: Any) -> str:
    """Neutralise spreadsheet formula injection."""
    text = "" if value is None else str(value)
    if text.startswith(_FORMULA_PREFIXES):
        return "'" + text
    return text


def _row_ids(ids: list[Any], total: Any) -> str:
    shown = ", ".join(str(i) for i in ids[:10])
    more = f" (+{int(total) - min(len(ids), 10)} more)" if total and int(total) > 10 else ""
    return f"row {shown}{more}" if len(ids) == 1 else f"rows {shown}{more}"


def _evidence_label(e: dict[str, Any]) -> str:
    if e.get("type") == "dataset_rows":
        kind = str(e.get("dataset_kind") or "").replace("_", " ")
        return (
            f"{kind.capitalize()} v{e.get('version_number')} · {e.get('label')} · "
            f"{_row_ids(e.get('row_ids') or [], e.get('row_count'))}"
        )
    if e.get("page_number"):
        return f"Page {e['page_number']} ({e.get('ref')})"
    if e.get("paragraph_number"):
        return f"Paragraph {e['paragraph_number']} ({e.get('ref')})"
    return str(e.get("ref") or "")


def _evidence_text(e: dict[str, Any]) -> str:
    if e.get("type") == "dataset_rows":
        cols = e.get("columns") or []
        return " | ".join(
            ", ".join(f"{c}={v}" for c, v in zip(cols, row, strict=False))
            for row in (e.get("rows") or [])[:5]
        )
    return str(e.get("quote") or "")


def _scope_datasets(scope: dict[str, Any]) -> list[str]:
    return [
        f"{str(d['kind']).replace('_', ' ').capitalize()}: {d['dataset_name']} — version "
        f"{d['version_number']} ({d['row_count']} rows, period {d.get('period_start') or '?'} "
        f"to {d.get('period_end') or '?'}) SHA-256 {d['parquet_sha256']}"
        for d in scope.get("datasets") or []
    ]


def _scope_rule_pack(scope: dict[str, Any]) -> str | None:
    rp = scope.get("rule_pack")
    if not rp:
        return None
    synthetic = " — synthetic, not real regulation" if rp.get("is_synthetic") else ""
    return (
        f"{rp['name']} ({rp['jurisdiction']}) — version {rp['version']}{synthetic}; "
        f"values as of {scope.get('as_of_date')}"
    )


_env.filters["evidence_label"] = _evidence_label
_env.globals["scope_datasets"] = _scope_datasets
_env.globals["scope_rule_pack"] = _scope_rule_pack
_env.filters["human"] = lambda s: (s or "").replace("_", " ")


def finding_origin(f: dict[str, Any]) -> str:
    ai = f.get("ai_suggestion")
    if ai:
        label = "mock provider, placeholder text" if ai.get("provider") == "mock" else ""
        model = f"{ai.get('provider')} · {ai.get('model')}"
        return f"AI suggestion accepted by a reviewer ({label or model})"
    if f.get("is_manual"):
        return "Added manually by a reviewer"
    return "Deterministic check"


_env.filters["origin"] = finding_origin

HTML_TEMPLATE = _env.from_string(
    """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Review report — {{ r.review.title }} (v{{ r.report_version }})</title>
<style>
body{font-family:system-ui,-apple-system,"Segoe UI",Tahoma,sans-serif;color:#0f172a;margin:2rem auto;max-width:900px;padding:0 1rem;line-height:1.5}
h1{color:#14284b;font-size:1.6rem;margin-bottom:.25rem}h2{color:#14284b;font-size:1.15rem;border-bottom:2px solid #0f766e;padding-bottom:.25rem;margin-top:2rem}
table{border-collapse:collapse;width:100%;font-size:.9rem}td,th{border:1px solid #cbd5e1;padding:.4rem .5rem;text-align:start;vertical-align:top}
th{background:#f1f5f9}.muted{color:#475569}.badge{display:inline-block;border-radius:4px;padding:0 .4rem;font-size:.8rem;background:#e2e8f0}
.synthetic{background:#fef3c7;border:1px solid #f59e0b;padding:.5rem .75rem;border-radius:6px}
.disclaimer{background:#f8fafc;border-inline-start:4px solid #0f766e;padding:.75rem 1rem}
blockquote{margin:.25rem 0;padding:.25rem .75rem;border-inline-start:3px solid #94a3b8;background:#f8fafc;unicode-bidi:plaintext}
@media print{body{margin:0}a{color:inherit}}
</style></head><body>
<p class="muted">Saqient Compliance Workspace · Review report version {{ r.report_version }}</p>
<h1>{{ r.review.title }}</h1>
<p>Organisation: <strong>{{ r.organization }}</strong></p>
{% if r.review.is_demo or r.organization_is_demo or r.scope.checklist_kind == 'synthetic_demo' %}
<p class="synthetic">Contains synthetic demonstration content — not legal guidance.</p>{% endif %}
<p>Signed off by <strong>{{ r.signed_off_by }}</strong> at {{ r.signed_off_at }}</p>

<h2>Scope</h2>
<table>
{% if r.scope.document_title %}<tr><th>Document</th><td>{{ r.scope.document_title }} — version {{ r.scope.document_version }} ({{ r.scope.file_format|upper }}, {{ r.scope.original_filename }})<br><span class="muted">SHA-256 {{ r.scope.sha256 }}</span></td></tr>{% endif %}
{% for d in scope_datasets(r.scope) %}<tr><th>Dataset</th><td>{{ d }}</td></tr>{% endfor %}
{% if scope_rule_pack(r.scope) %}<tr><th>Rule pack</th><td>{{ scope_rule_pack(r.scope) }}</td></tr>{% endif %}
<tr><th>Checklist</th><td>{{ r.scope.checklist_name }} — version {{ r.scope.checklist_version }} ({{ r.scope.checklist_kind|human }}, {{ r.scope.requirement_count }} requirements)
{% if r.scope.checklist_disclaimer %}<br><em>{{ r.scope.checklist_disclaimer }}</em>{% endif %}</td></tr>
<tr><th>Engine</th><td>{{ r.engine.mode }} · {{ r.engine.version }} · run {{ r.engine.run_started_at }} → {{ r.engine.run_finished_at }}</td></tr>
</table>

<h2>Extraction and processing warnings</h2>
{% set warns = r.extraction_warnings + r.run_warnings %}
{% if warns %}<ul>{% for w in warns %}<li>{{ w }}</li>{% endfor %}</ul>{% else %}<p class="muted">None recorded.</p>{% endif %}

<h2>Findings ({{ r.findings|length }})</h2>
{% for f in r.findings %}
<h3>{{ loop.index }}. {{ f.title }}</h3>
<table>
<tr><th>Severity</th><td>{{ f.severity }}</td><th>Reviewer decision</th><td><span class="badge">{{ f.status|human }}</span></td></tr>
<tr><th>Requirement</th><td>{{ f.requirement_code or 'Manual finding' }}</td><th>Automated outcome</th><td>{{ (f.automated_outcome or 'n/a')|human }}</td></tr>
<tr><th>Origin</th><td colspan="3">{{ f|origin }}</td></tr>
<tr><th>Source reference</th><td colspan="3">{{ f.source_reference or '—' }}</td></tr>
<tr><th>Rationale</th><td colspan="3">{{ f.decision_rationale or '—' }} <span class="muted">{{ f.decided_by or '' }} {{ f.decided_at or '' }}</span></td></tr>
<tr><th>Remediation</th><td colspan="3">Owner: {{ f.owner or 'unassigned' }} · Due: {{ f.due_date or '—' }}<br>{{ f.remediation_notes }}</td></tr>
<tr><th>Evidence</th><td colspan="3">{% for e in f.evidence %}<div>{{ e|evidence_label }}{% if e.type == 'dataset_rows' %}
<table><tr>{% for c in e.columns %}<th>{{ c }}</th>{% endfor %}</tr>{% for row in e.rows %}<tr>{% for v in row %}<td>{{ v if v is not none else '' }}</td>{% endfor %}</tr>{% endfor %}</table>
{% else %}<blockquote>{{ e.quote }}</blockquote>{% endif %}</div>{% else %}<span class="muted">No matching text in the document (absence noted by the check).</span>{% endfor %}</td></tr>
</table>
<p class="muted">{{ f.description }}</p>
{% else %}<p class="muted">No findings were recorded.</p>{% endfor %}

<h2>All check results</h2>
<table><tr><th>Requirement</th><th>Outcome</th><th>Detail</th></tr>
{% for c in r.check_results %}<tr><td>{{ c.code }} — {{ c.title }}</td><td>{{ c.outcome|human }}</td><td>{{ c.message }}</td></tr>{% endfor %}
</table>

<h2>Limitations</h2>
<ul>{% for l in r.limitations %}<li>{{ l }}</li>{% endfor %}</ul>
<h2>Disclaimer</h2>
<p class="disclaimer">{{ r.disclaimer }}</p>
</body></html>"""
)


def render_html(content: dict[str, Any]) -> str:
    return HTML_TEMPLATE.render(r=content)


CSV_COLUMNS = [
    "report_version",
    "finding_id",
    "requirement_code",
    "title",
    "severity",
    "automated_outcome",
    "reviewer_status",
    "decision_rationale",
    "decided_by",
    "decided_at",
    "owner",
    "due_date",
    "evidence_refs",
    "evidence_quotes",
    "source_reference",
    "origin",
]


def render_csv(content: dict[str, Any]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_COLUMNS)
    for f in content["findings"]:
        writer.writerow(
            [
                csv_safe(v)
                for v in [
                    content["report_version"],
                    f["id"],
                    f["requirement_code"],
                    f["title"],
                    f["severity"],
                    f["automated_outcome"],
                    f["status"],
                    f["decision_rationale"],
                    f["decided_by"],
                    f["decided_at"],
                    f["owner"],
                    f["due_date"],
                    "; ".join(_evidence_label(e) for e in f["evidence"]),
                    " | ".join(_evidence_text(e) for e in f["evidence"]),
                    f["source_reference"],
                    finding_origin(f),
                ]
            ]
        )
    return buf.getvalue()


def render_pdf(content: dict[str, Any]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    navy = colors.HexColor("#14284b")
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], textColor=navy, fontSize=16)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], textColor=navy, fontSize=12)
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=9, leading=12)
    small = ParagraphStyle("small", parent=body, fontSize=8, textColor=colors.HexColor("#475569"))

    def p(text: Any, style: ParagraphStyle = body) -> Paragraph:
        return Paragraph(escape("" if text is None else str(text)), style)

    r = content
    s = r["scope"]
    story: list[Any] = [
        p(f"Saqient Compliance Workspace · Review report version {r['report_version']}", small),
        p(r["review"]["title"], h1),
        p(f"Organisation: {r['organization']}"),
        p(f"Signed off by {r['signed_off_by']} at {r['signed_off_at']}"),
    ]
    if (
        r["review"]["is_demo"]
        or r.get("organization_is_demo")
        or s["checklist_kind"] == "synthetic_demo"
    ):
        story.append(p("Contains synthetic demonstration content — not legal guidance.", body))
    story += [Spacer(1, 4 * mm), p("Scope", h2)]
    scope_rows = []
    if s.get("document_title"):
        scope_rows.append(
            [
                p("Document"),
                p(
                    f"{s['document_title']} — version {s['document_version']} "
                    f"({s['file_format'].upper()}, {s['original_filename']}) "
                    f"SHA-256 {s['sha256']}"
                ),
            ]
        )
    scope_rows += [[p("Dataset"), p(d)] for d in _scope_datasets(s)]
    rule_pack = _scope_rule_pack(s)
    if rule_pack:
        scope_rows.append([p("Rule pack"), p(rule_pack)])
    scope_rows += [
        [
            p("Checklist"),
            p(
                f"{s['checklist_name']} — version {s['checklist_version']} "
                f"({s['checklist_kind'].replace('_', ' ')}). "
                f"{s['checklist_disclaimer']}"
            ),
        ],
        [p("Engine"), p(f"{r['engine']['mode']} · {r['engine']['version']}")],
    ]
    t = Table(scope_rows, colWidths=[30 * mm, 140 * mm])
    t.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story.append(t)
    warns = r["extraction_warnings"] + r["run_warnings"]
    story.append(p("Extraction and processing warnings", h2))
    story += [p(f"• {w}") for w in warns] or [p("None recorded.", small)]
    story.append(p(f"Findings ({len(r['findings'])})", h2))
    for i, f in enumerate(r["findings"], start=1):
        story.append(
            p(f"{i}. {f['title']}", ParagraphStyle("fh", parent=body, fontName="Helvetica-Bold"))
        )
        rows = [
            [p("Severity"), p(f["severity"]), p("Decision"), p(f["status"].replace("_", " "))],
            [
                p("Requirement"),
                p(f["requirement_code"] or "Manual finding"),
                p("Automated"),
                p((f["automated_outcome"] or "n/a").replace("_", " ")),
            ],
            [
                p("Rationale"),
                p(f"{f['decision_rationale'] or '—'} ({f['decided_by'] or ''})"),
                p("Owner / due"),
                p(f"{f['owner'] or 'unassigned'} / {f['due_date'] or '—'}"),
            ],
        ]
        ev = "; ".join(f"{_evidence_label(e)}: “{_evidence_text(e)}”" for e in f["evidence"])
        rows.append(
            [
                p("Evidence"),
                p(ev or "No matching text (absence noted by the check)."),
                p("Source"),
                p(f["source_reference"] or "—"),
            ]
        )
        rows.append([p("Origin"), p(finding_origin(f)), p(""), p("")])
        ft = Table(rows, colWidths=[22 * mm, 68 * mm, 22 * mm, 58 * mm])
        ft.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        story += [ft, Spacer(1, 3 * mm)]
    if not r["findings"]:
        story.append(p("No findings were recorded.", small))
    story.append(p("Limitations", h2))
    story += [p(f"• {lim}") for lim in r["limitations"]]
    story.append(p("Disclaimer", h2))
    story.append(p(r["disclaimer"]))
    story.append(Spacer(1, 3 * mm))
    story.append(
        p(
            "Note: Arabic text is not shaped correctly in PDF exports; use the HTML "
            "report for Arabic content.",
            small,
        )
    )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        title=f"Review report v{r['report_version']}",
        author="Saqient Compliance Workspace",
        leftMargin=18 * mm,
        rightMargin=18 * mm,
    )
    doc.build(story)
    return buf.getvalue()
