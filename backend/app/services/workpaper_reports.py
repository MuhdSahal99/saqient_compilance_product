"""HTML, PDF and CSV exports of a signed-off workpaper snapshot.

Each line shows its amount or result, the formula id and steps, the rule versions
it read (unverified ones flagged) and its evidence. The content comes only from
the immutable snapshot, so an export always matches what was signed off.
"""

from __future__ import annotations

import csv
import io
from typing import Any
from xml.sax.saxutils import escape

from jinja2 import Environment, select_autoescape

from app.services.reports import _rule_line, csv_safe

DISCLAIMER = (
    "Prepared for review by a qualified tax adviser. Results are proposals computed from "
    "the inputs and rule pack shown; this is not a tax return, a filing or a determination "
    "that any relief, exemption or threshold applies."
)
SYNTHETIC = "Contains synthetic demonstration content — not legal guidance."


def evidence_text(e: dict[str, Any]) -> str:
    kind = e.get("kind")
    if kind == "source_block":
        where = (
            f"page {e['page_number']}"
            if e.get("page_number") is not None
            else f"paragraph {e.get('paragraph_number')}"
        )
        quote = (e.get("quote") or "").strip()
        return f"{e.get('document_title')} v{e.get('document_version')}, {where} ({e.get('ref')}): “{quote}”"
    if kind == "dataset_rows":
        ids = e.get("row_ids") or []
        shown = ", ".join(str(i) for i in ids[:10]) + (
            f" (+{len(ids) - 10} more)" if len(ids) > 10 else ""
        )
        extra = f"; accounts {', '.join(e['account_codes'])}" if e.get("account_codes") else ""
        return f"{e.get('dataset_name')} v{e.get('version_number')}, rows {shown}{extra}"
    if kind == "workpaper_line":
        return f"Workpaper {e.get('workpaper_title')}, line {e.get('line_key')}"
    if kind == "loss_register":
        return f"Loss register before {e.get('before')}: {len(e.get('entry_ids') or [])} entries, balance {e.get('balance')}"
    return str(kind)


def result_text(line: dict[str, Any]) -> str:
    if line.get("amount") is not None:
        return str(line["amount"])
    return (line.get("value") or "").replace("_", " ")


def _unverified(c: dict[str, Any]) -> bool:
    return bool(c.get("warnings"))


_env = Environment(autoescape=select_autoescape(default=True))
_env.globals.update(rule_line=_rule_line, evidence_text=evidence_text, result_text=result_text)
_env.filters["human"] = lambda s: (s or "").replace("_", " ")

HTML = _env.from_string(
    """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Workpaper — {{ c.title }} (v{{ c.version }})</title>
<style>
body{font-family:system-ui,-apple-system,"Segoe UI",Tahoma,sans-serif;color:#0f172a;margin:2rem auto;max-width:960px;padding:0 1rem;line-height:1.5}
h1{color:#14284b;font-size:1.5rem;margin-bottom:.25rem}h2{color:#14284b;font-size:1.1rem;border-bottom:2px solid #0f766e;padding-bottom:.25rem;margin-top:2rem}
table{border-collapse:collapse;width:100%;font-size:.85rem}td,th{border:1px solid #cbd5e1;padding:.35rem .5rem;text-align:start;vertical-align:top}
th{background:#f1f5f9}.muted{color:#475569}.num{text-align:end;font-variant-numeric:tabular-nums;unicode-bidi:plaintext}
.synthetic{background:#fef3c7;border:1px solid #f59e0b;padding:.5rem .75rem;border-radius:6px}
.warn{background:#fff7ed;border:1px solid #fb923c;padding:.5rem .75rem;border-radius:6px}
.disclaimer{background:#f8fafc;border-inline-start:4px solid #0f766e;padding:.75rem 1rem}
ul{margin:.25rem 0;padding-inline-start:1.1rem}
@media print{body{margin:0}}
</style></head><body>
<p class="muted">Saqient Compliance Workspace · Workpaper snapshot version {{ c.version }}</p>
<h1>{{ c.title }}</h1>
{% if c.is_demo %}<p class="synthetic">{{ synthetic }}</p>{% endif %}
<p class="disclaimer">{{ disclaimer }}</p>
<table>
<tr><th>Entity</th><td>{{ c.entity.name }}</td></tr>
<tr><th>Kind</th><td>{{ c.kind|human }}</td></tr>
<tr><th>Period</th><td>{{ c.period_start }} to {{ c.period_end }} ({{ c.currency }})</td></tr>
<tr><th>Calculation</th><td>{{ c.calc_version }} · computed {{ c.computed_at }} · result SHA-256 {{ c.result_hash }}</td></tr>
<tr><th>Rule prefix</th><td>{{ c.rules_prefix }} (pack version {{ c.rule_pack_version_id }})</td></tr>
<tr><th>Signed off</th><td>{{ c.signed_off_by }}</td></tr>
</table>
{% if c.warnings %}<h2>Unverified rules</h2><div class="warn"><ul>{% for w in c.warnings %}<li>{{ w }}</li>{% endfor %}</ul></div>{% endif %}
<h2>Inputs</h2>
<table><tr><th>Line</th><th>Category</th><th class="num">Amount / value</th><th>Evidence and note</th></tr>
{% for l in c.lines if l.source == 'manual' %}
<tr><td>{{ l.label }}<br><span class="muted">{{ l.line_key }}</span></td><td>{{ l.category|human }}</td><td class="num">{{ result_text(l) }}</td>
<td>{% if l.evidence %}<ul>{% for e in l.evidence %}<li>{{ evidence_text(e) }}</li>{% endfor %}</ul>{% else %}<span class="muted">No evidence linked</span>{% endif %}{% if l.note %}<p>{{ l.note }}</p>{% endif %}</td></tr>
{% endfor %}</table>
<h2>Computed lines</h2>
<table><tr><th>Line</th><th class="num">Result</th><th>How it was computed</th><th>Rules used</th></tr>
{% for l in c.lines if l.source == 'computed' %}
<tr><td>{{ l.label }}<br><span class="muted">{{ l.formula_id }}</span></td><td class="num">{{ result_text(l) }}</td>
<td><ul>{% for s in l.explanation %}<li>{{ s.label }}: {{ s.expression }} = {{ s.value }}</li>{% endfor %}</ul></td>
<td>{% for r in l.rule_snapshots %}<div>{{ rule_line(r) }}</div>{% endfor %}</td></tr>
{% endfor %}</table>
</body></html>"""
)


def render_html(c: dict[str, Any]) -> str:
    return HTML.render(c=c, disclaimer=DISCLAIMER, synthetic=SYNTHETIC)


CSV_COLUMNS = [
    "source",
    "section",
    "line_key",
    "label",
    "category",
    "amount",
    "value",
    "formula_id",
    "steps",
    "rules",
    "unverified_rules",
    "evidence",
    "note",
]


def render_csv(c: dict[str, Any]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "# " + csv_safe(c["title"]),
            f"v{c['version']}",
            c["period_start"],
            c["period_end"],
            c["currency"],
        ]
    )
    w.writerow(["# " + DISCLAIMER])
    if c.get("is_demo"):
        w.writerow(["# " + SYNTHETIC])
    w.writerow(CSV_COLUMNS)
    for ln in c["lines"]:
        rules = ln.get("rule_snapshots") or []
        w.writerow(
            [
                csv_safe(v)
                for v in (
                    ln["source"],
                    ln["section"],
                    ln["line_key"],
                    ln["label"],
                    ln["category"],
                    ln.get("amount"),
                    ln.get("value"),
                    ln.get("formula_id"),
                    " | ".join(
                        f"{s['label']}: {s['expression']} = {s['value']}"
                        for s in ln.get("explanation") or []
                    ),
                    " | ".join(_rule_line(r) for r in rules),
                    sum(1 for r in rules if r.get("verification_status") != "verified"),
                    " | ".join(evidence_text(e) for e in ln.get("evidence") or []),
                    ln.get("note"),
                )
            ]
        )
    return buf.getvalue()


def render_pdf(c: dict[str, Any]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    navy = colors.HexColor("#14284b")
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], textColor=navy, fontSize=15)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], textColor=navy, fontSize=11)
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=8, leading=10)

    def p(text: Any, style: ParagraphStyle = body) -> Paragraph:
        return Paragraph(escape("" if text is None else str(text)), style)

    grid = TableStyle(
        [
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]
    )
    story: list[Any] = [
        p(f"Saqient Compliance Workspace · Workpaper snapshot version {c['version']}"),
        p(c["title"], h1),
        p(
            f"{c['entity']['name']} · {c['kind'].replace('_', ' ')} · {c['period_start']} to {c['period_end']} ({c['currency']})"
        ),
        p(
            f"{c['calc_version']} · result SHA-256 {c['result_hash']} · signed off by {c.get('signed_off_by')}"
        ),
    ]
    if c.get("is_demo"):
        story.append(p(SYNTHETIC))
    story += [Spacer(1, 2 * mm), p(DISCLAIMER)]
    if c.get("warnings"):
        story += [p("Unverified rules", h2), *[p(w) for w in c["warnings"]]]
    inputs = [[p("Line"), p("Category"), p("Amount / value"), p("Evidence and note")]]
    for ln in c["lines"]:
        if ln["source"] == "manual":
            ev = (
                "; ".join(evidence_text(e) for e in ln.get("evidence") or [])
                or "No evidence linked"
            )
            inputs.append(
                [
                    p(ln["label"]),
                    p(ln["category"]),
                    p(result_text(ln)),
                    p(f"{ev} {ln.get('note') or ''}"),
                ]
            )
    computed = [[p("Line"), p("Result"), p("How it was computed"), p("Rules used")]]
    for ln in c["lines"]:
        if ln["source"] == "computed":
            steps = "; ".join(
                f"{s['label']}: {s['expression']} = {s['value']}"
                for s in ln.get("explanation") or []
            )
            rules = "; ".join(_rule_line(r) for r in ln.get("rule_snapshots") or [])
            computed.append(
                [p(f"{ln['label']} ({ln['formula_id']})"), p(result_text(ln)), p(steps), p(rules)]
            )
    widths = [60 * mm, 30 * mm, 100 * mm, 80 * mm]
    story += [p("Inputs", h2), Table(inputs, colWidths=widths, style=grid, repeatRows=1)]
    story += [p("Computed lines", h2), Table(computed, colWidths=widths, style=grid, repeatRows=1)]
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=landscape(A4), title=c["title"]).build(story)
    return buf.getvalue()
