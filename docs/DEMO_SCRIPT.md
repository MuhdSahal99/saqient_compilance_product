# Demo script (about 10 minutes)

Everything shown is synthetic demonstration content, not legal guidance. Do
not upload real customer, bank, health or personal documents during a demo.
Do not present the value hypotheses in docs/PRODUCT_SPEC.md as results.

## Setup

```bash
docker compose up -d --build
docker compose exec api python -m app.seed --reset
# http://localhost:8080 — password for every demo user: Demo-Password-2026!
```

| User | Role |
|---|---|
| reviewer@alpha.example | Reviewer (main presenter account) |
| analyst@alpha.example | Analyst |
| viewer@alpha.example | Read-only viewer |
| admin@alpha.example | Organisation admin |
| reviewer@beta.example | Reviewer in a second organisation (tenant isolation) |

Upload file: `samples/synthetic-vendor-policy.pdf` (or `.docx` / `.txt`).

## 1. The problem (1 min, no clicks)

Reviews today run on spreadsheets, email and memory: checklists are not
versioned, findings are not linked to the clause that supports them,
remediation slips, and sign-off is informal. The goal of the workspace is to
make one review structured, evidence-linked and traceable from upload to a
signed-off report. AI is switched off; everything shown is deterministic text
matching plus human decisions.

## 2. Overview (1 min) — sign in as reviewer@alpha.example

- Point out the demo banner and "Synthetic" labels.
- The numbers are operational counts from this organisation's data, not a
  compliance score. Coverage is defined on screen: "The proportion of
  checklist items reviewed."

## 3. Upload and extraction (2 min)

- Documents → Upload document → choose the sample PDF, type "Policy".
- Note the upload hint: scanned PDFs are not supported (no OCR) and files are
  validated by type and signature but not scanned for malware.
- Open the document: status moves from Queued to Ready (background worker).
  Show extracted text with page numbers. Search the text for "subcontractors".
- Optional: upload the same file a second time to show duplicate detection.

## 4. Versioned checklist (1 min)

- Checklists → "Policy Baseline Checklist (synthetic demo)" v1.
- Show the disclaimer, each requirement's automated check and reviewer
  instructions, and that published versions cannot change.

## 5. Run a review and inspect evidence (2 min)

- From the document: Start review → title → Create and run checks.
- Findings appear beside the document. Select "No absolute assurance
  language": the highlighted passage "100% secure" is shown in the document
  pane with its page reference.
- Explain "Automated outcome (not a reviewer decision)": a match is not proof
  of compliance, and a missing match is not automatically a violation.
- "All check results" tab shows every requirement, including matches.

## 6. Decide, assign, sign off (2 min)

- Confirm "No absolute assurance language" → assign Demo Analyst with a due date.
- Dismiss "Periodic access review is required" — show that a rationale is required.
- Accept risk on "Management approval is evidenced" with a rationale.
- Sign off review. Decisions are now locked; a report version is frozen.

## 7. Report and traceability (1 min)

- Reports tab → export HTML, PDF and CSV. The report lists document version,
  checklist version, engine version, evidence references and the disclaimer.
- Activity page: who did what, when (an application log, not tamper-proof).
- Tasks: sign in as analyst@alpha.example to see "Assigned to me" and mark
  the remediation ready for re-review.

## 8. Arabic and isolation (optional, 1 min)

- Switch to العربية: the layout flips to right-to-left.
- Sign in as reviewer@beta.example: none of Alpha's documents or reviews are
  visible; pasting an Alpha review URL returns "Page not found".

## What not to say

- Not "compliant", "certified", "approved by regulator", "ISO", "secure
  against all threats", "AI-powered analysis" or any time-saving figure.
