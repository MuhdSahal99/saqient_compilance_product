# Product specification — Saqient Compliance Workspace (MVP)

## Problem

Audit, compliance and risk teams in GCC organisations review policies,
contracts, procedures and evidence documents largely by hand:

- Checklists live in spreadsheets, Word files or people's heads and are not
  versioned, so reviewers apply different criteria and nobody can say which
  checklist version was used.
- Findings are written in emails or side documents with no link to the page or
  clause that supports them.
- Remediation is tracked over email/chat; owners, deadlines and status get lost.
- Sign-off is informal; there is no reliable record of who decided what, when.
- Bilingual (Arabic/English) documents add effort; many tools handle RTL poorly.
- Sensitive documents often cannot be sent to foreign public AI services
  (data residency, confidentiality, sector rules).

Consequences: slow and expensive reviews, inconsistent results, evidence that
is hard to retrieve for auditors, remediation that slips, and manual report
assembly.

**What Saqient does:** one secure workspace where a document review is
structured, consistent, evidence-linked and auditable from upload to signed-off
report. AI assistance may be added later, under the organisation's own
data-control requirements. It is disabled in this MVP.

## Value hypotheses (unvalidated — never present as results)

- Less time per review.
- More consistent findings between reviewers and cycles.
- Faster evidence retrieval for auditors.
- Better remediation follow-through.

The product must not display metrics, testimonials or claims implying these
have been demonstrated.

## Users and roles

Primary: internal audit, compliance and risk teams (e.g. banking, insurance,
healthcare, government-linked entities). Secondary: audit/advisory firms.

| Role | Can |
|---|---|
| Organisation admin | Everything below + manage members and settings |
| Reviewer | Upload, create reviews, run checks, decide findings, assign remediation, sign off, author checklists |
| Analyst | Upload, create reviews, run checks, add manual findings and comments, update remediation on findings assigned to them |
| Read-only viewer | View documents, reviews, findings, reports, activity |

## Feature → problem map

| Feature | Problem addressed |
|---|---|
| Versioned checklists (publish = immutable) | Consistent, repeatable criteria; reviews record the exact version used |
| Deterministic checks | Fast first pass for required sections/terms, no AI dependency |
| Evidence-linked findings | Every finding points to stored source text (page or paragraph) |
| Remediation assignment | Owners, due dates, status, overdue visibility (in-app; no external notifications yet) |
| Reviewer decisions + sign-off | Formal, recorded approval; signed-off reports are immutable versions |
| Activity / audit log | Traceability of actions and decisions (not tamper-proof) |
| Report export (HTML/PDF/CSV) | Removes manual report assembly |
| Arabic/English + RTL | Native regional language support in the UI |
| Tenant isolation, private storage, AI disabled | Confidentiality and data-residency concerns |
| Provider abstraction (Jais/Falcon reserved) | Future self-hosted / in-region AI, off by default |

## Core workflow (MVP acceptance)

1. User signs in; organisation resolved server-side.
2. Uploads a PDF (text-based), DOCX or TXT. File is validated (extension, MIME,
   signature, size, pages), stored privately, hashed, and queued for extraction.
3. Extraction produces source blocks with stable ids and refs (PDF page;
   DOCX/TXT paragraph).
4. User creates a review: document version + published checklist version.
5. Engine runs deterministic checks; each requirement gets an outcome:
   match found / no match found / needs human review / processing error
   (reviewer may mark not applicable with a reason).
6. Items needing attention become **proposed** findings with evidence.
7. Reviewer confirms or dismisses each finding (rationale required for
   dismissal and accepted risk), assigns remediation owner and due date.
8. Reviewer signs off → immutable report snapshot (version n).
9. Report exported as HTML, PDF or CSV with versions, evidence, limitations and
   disclaimer.

## Explicit non-goals for the MVP

- Certifying compliance or producing a "compliance score".
- Shipping real regulatory content. Seeded checklists are synthetic and say
  "Synthetic demonstration content — not legal guidance."
- AI analysis of any kind (provider abstraction only).
- Malware scanning (pilot-readiness requirement, see KNOWN_LIMITATIONS).
- MFA, SSO, external email/notification delivery (backlog).

## Overview dashboard

Database-derived counts only: documents processed, active reviews, proposed
and confirmed findings, open remediation tasks, overdue remediation, severity
distribution, job failures. If checklist coverage is shown it is labelled
"The proportion of checklist items reviewed." — not a probability of compliance.
