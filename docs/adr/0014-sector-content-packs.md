# ADR 0014 — Sector content packs, FS draft, lease and depreciation, AI opt-in

Status: accepted (2026-10-19)

## Context
Phase F adds sector content (AML/CFT, banking and IFRS 9, IFRS 17, listed company
disclosures, ESG S1/S2, ESR/UBO), a financial statements draft from the mapped trial
balance, IFRS 16 lease and depreciation recalculations, and an AI assist. None of this
may become an invented regulation or an unreviewed conclusion.

## Decision
- **Packs are data, not code.** Each pack is a JSON manifest under
  `backend/app/packs/data/` validated by `PackManifest`: semver, sector, `jurisdiction`
  `generic`, `status` `draft`, `synthetic` true, the synthetic disclaimer verbatim, at
  least one open question, checklist requirements whose check configs must parse for
  the current engine, and rules that each carry a TODO and the pack's prefix.
- **Installing copies drafts.** An org admin installs a pack version once
  (`content_pack_installs`, unique per org, pack and version, with the manifest
  SHA-256). It creates draft checklist versions and a draft rule pack; people review,
  verify and publish them through the existing flows. Rules stay `draft` until a human
  verifies them.
- **FS draft and lease are calculations** in `app/calc/fs.py` (`fs_draft`,
  `lease_ifrs16`) with golden files. The FS draft takes lead schedules by section,
  reverses credit signs for presentation, balances assets against liabilities, equity
  and the year's result, and compares each note total with its face line within
  `<prefix>.fs_note_tolerance`. The lease discount rate is the preparer's input.
- **Depreciation is an engine check** (`deterministic-1.6.0`, `depreciation_recalc`)
  over the new `fixed_assets` dataset kind, with conventions stated in
  `app/engine/fa_checks.py` and `<prefix>.dep_tolerance`.
- **AI needs two switches.** The deployment flag (`AI_ENABLED`, provider) and an org
  admin's opt-in (`organizations.ai_opt_in`, audited). The opt-in is re-checked when the
  job runs. Suggestions stay suggestions; quotes are validated against stored blocks;
  provider and model are recorded on the run. Only the mock provider is tested.

## Consequences
Shipped packs are demonstrations that teams must rewrite against verified sources; the
FS draft is a working draft, not financial statements; depreciation differences are
leads because entity policies differ.
