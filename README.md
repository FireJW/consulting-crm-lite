# Consulting CRM Lite

Local-first CLI for AI workflow consulting. It imports leads from CSV, scores
fit, recommends a service package, generates delivery artifacts, tracks
follow-ups, and blocks case-study export until explicit client approval is
recorded.

This is a portfolio-ready version of a small consulting operations tool: the
workflow is useful, the data boundary is conservative, and the public sample
data is synthetic.

- Docs site: https://firejw.github.io/consulting-crm-lite/
- Demo runbook: [docs/demo-runbook.md](docs/demo-runbook.md)
- Privacy notes: [docs/security-and-privacy.md](docs/security-and-privacy.md)
- Case-study framing: [docs/case-study.md](docs/case-study.md)

## What It Does

- Reads lead intake rows from CSV.
- Stores working state in a local SQLite database under `.local/`.
- Hashes contact fields and uses anonymized aliases such as `Client 1` in
  exported status views.
- Scores leads across pain intensity, budget, urgency, expertise fit,
  repeatability, and case-study potential.
- Generates proposals, delivery reports, discovery notes, delivery checklists,
  follow-up plans, Obsidian preview notes, review packets, and anonymized JSON
  snapshots.
- Requires `client_approved_for_case_study=true` before exporting a case-study
  draft.

## Why This Exists

Early consulting work often starts in scattered forms, notes, spreadsheets, and
manual follow-up reminders. This repo turns that loose process into a small,
auditable CLI workflow without adding a SaaS account, external API, or live
knowledge-base write.

The point is not to be a full CRM. The point is to show a practical operating
loop for AI workflow consulting:

```text
CSV lead -> local SQLite -> anonymized scoring -> proposal -> delivery tracking
         -> review packet -> approval-gated case-study draft
```

## Quick Start

Requires Python 3.10+ and only uses the Python standard library.

```powershell
py .\consulting.py init-db
py .\consulting.py import-leads --csv .\examples\leads.csv --lang bilingual
py .\consulting.py score-leads --lang bilingual
py .\consulting.py list-leads
py .\consulting.py generate-proposal --lead-id 1 --out .local\proposal-1.md --lang bilingual
py .\consulting.py generate-delivery-report --project-id 1 --out .local\report-1.md --lang bilingual
py .\consulting.py generate-delivery-checklist --project-id 1 --out .local\checklist-1.md --lang bilingual
py .\consulting.py generate-followup --project-id 1 --out .local\followup-1.md --lang bilingual
py .\consulting.py validate-project --project-id 1
py .\consulting.py export-review-packet --project-id 1 --output-dir .local\review-packet-preview
```

Default database:

```text
.local\consulting-crm.sqlite
```

`.local/` is gitignored so real lead data and generated working files stay out
of version control.

## Case Study Gate

Case-study export is deliberately blocked by default:

```powershell
py .\consulting.py export-case-study --project-id 1 --out .local\case-study-1.md
```

The command exits non-zero until approval is recorded:

```powershell
py .\consulting.py approve-case-study --project-id 1 --approved-by "operator"
py .\consulting.py export-case-study --project-id 1 --out .local\case-study-1.md --lang bilingual
py .\consulting.py revoke-case-study-approval --project-id 1
```

`approve-case-study`, `revoke-case-study-approval`, and successful
`export-case-study` calls also support `--format json` for automation.

## CLI Surface

| Area | Commands |
| --- | --- |
| Setup and intake | `init-db`, `import-leads`, `score-leads` |
| Read-only status | `list-leads`, `list-projects`, `show-project`, `dashboard`, `validate-project`, `what-remains` |
| Delivery artifacts | `generate-proposal`, `record-discovery-call`, `generate-delivery-report`, `generate-delivery-checklist`, `generate-followup` |
| Delivery tracking | `list-delivery-checklist`, `mark-checklist-done`, `reopen-checklist-item`, `list-followups`, `mark-followup-done`, `reopen-followup` |
| Local exports | `export-obsidian`, `export-json-snapshot`, `export-review-packet` |
| Case-study gate | `approve-case-study`, `revoke-case-study-approval`, `export-case-study` |

Most read-only views support `--format json` for machine-readable handoffs.

## Privacy Model

- No external API calls.
- No account connection.
- No live Obsidian vault writes.
- Preview exports are restricted to `.local`, `.tmp`, `tmp`, or paths that
  include `preview`.
- Status and export views use anonymized aliases by default.
- Contact identity is used only to compute a short local hash for duplicate
  detection.

See [docs/security-and-privacy.md](docs/security-and-privacy.md) for the full
public-facing boundary.

## Testing

```powershell
py -m unittest discover -s tests -v
```

The test suite covers anonymization, lead scoring, delivery artifact generation,
JSON status views, preview-only export restrictions, follow-up/checklist state,
review packets, snapshots, and the case-study approval gate.

## Non-Goals

- Not a multi-user hosted CRM.
- Not a replacement for a real customer database.
- Not a sender for emails, messages, or social posts.
- Not a live-vault writer; exports are preview/local by design.
