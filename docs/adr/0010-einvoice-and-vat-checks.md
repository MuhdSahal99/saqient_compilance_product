# ADR 0010 — E-invoice validation and VAT checks driven by rule packs

Status: accepted (2026-10-18)

## Decision
Engine `deterministic-1.2.0` adds e-invoice, readiness, master data and VAT return
checks (`app/engine/einvoice_checks.py`, `master_data_checks.py`, `vat_checks.py`).
1.1.0 configs still parse and run unchanged.

- **Regulatory data is pack data.** Mandatory fields (restricted XPath), code lists,
  tax number shapes, rounding, QR tags, hash encoding, go-live waves, VAT box layouts,
  blocked categories and filing obligations are `json` rules validated by shape
  (`app/services/rule_schemas.py`). XSD schemas are zip bundles attached to a pack
  version (`rule_pack_files`), compiled with imports resolved only inside the bundle.
  Bundles and rules are verified by an admin with a source URL; synthetic ones cannot be.
- **Safe XML.** defusedxml first (no DTDs or entities), then lxml with entity
  resolution, DTD loading and network access off. ZIPs are checked for traversal,
  entry count and unpacked size.
- **One finding per failure kind.** A check can return finding groups; each becomes
  its own finding under the requirement, keyed by `findings.finding_key`
  (e.g. `mandatory:BT-1`, `box:P1T`). Evidence is the XML path, line and value
  (`type: xml`) or a computation with its formula (`type: computation`).
- **VAT treatment is client configuration.** An entity maps its ERP tax codes to a
  treatment and recoverability and names its VAT GL accounts; return boxes are
  recomputed from the registers with the pack's layout.
- **Reviews carry the context.** A review can name an entity, a tax period and
  e-invoices; period-based checks use the tax period.
- **Monitoring is sampling into reviews.** A monitor ranks new files by
  SHA-256(seed:file hash) and validates the first N in a new review; the seed, window
  and method are stored per run so the sample can be re-drawn.

## Why
Rates, schemas and deadlines change and differ by jurisdiction; keeping them as
versioned, verified data lets Bahrain or Oman be added without code, and every result
shows which unverified values it relied on.

## Open questions (rules stay draft until answered)
- The ZATCA invoice hash and QR tag 6 follow our reading of the published approach
  (C14N 1.0 over the invoice without UBLExtensions, Signature and the QR reference);
  this has not been compared with the official SDK. The encoding is a rule value.
- Official PINT-AE and ZATCA schema bundles and schematron rules are not shipped;
  admins upload them. Schematron is not evaluated.
