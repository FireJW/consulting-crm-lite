# Demo Runbook

This runbook shows the public-safe path from CSV intake to review packet. The
sample lead in `examples/leads.csv` is synthetic.

## 1. Initialize Local State

```powershell
py .\consulting.py init-db
```

This creates the default SQLite database at:

```text
.local\consulting-crm.sqlite
```

The `.local/` directory is ignored by git.

## 2. Import and Score a Lead

```powershell
py .\consulting.py import-leads --csv .\examples\leads.csv --lang bilingual
py .\consulting.py score-leads --lang bilingual
py .\consulting.py list-leads
py .\consulting.py list-leads --format json
```

Expected shape:

```text
L-0001 (Client 1)
classification=1v1 consultation fit
recommended_offer=workflow_sprint_3_session
```

The output uses `Client 1`; raw name, email, and company fields are not printed.

## 3. Generate Delivery Artifacts

```powershell
py .\consulting.py generate-proposal --lead-id 1 --out .local\proposal-1.md --lang bilingual
py .\consulting.py record-discovery-call --lead-id 1 --project-id 1 --summary "Current workflow relies on manual handoffs." --current-state "Manual research spreadsheet" --blockers "No repeatable intake" --desired-outcome "Reusable content offer" --next-step "Send workflow map" --out .local\discovery-1.md --lang bilingual
py .\consulting.py generate-delivery-report --project-id 1 --out .local\report-1.md --lang bilingual
py .\consulting.py generate-delivery-checklist --project-id 1 --out .local\checklist-1.md --lang bilingual
py .\consulting.py generate-followup --project-id 1 --out .local\followup-1.md --lang bilingual
```

## 4. Check Readiness

```powershell
py .\consulting.py dashboard
py .\consulting.py validate-project --project-id 1
py .\consulting.py what-remains --project-id 1
```

`validate-project` reports required delivery artifacts separately from the
case-study approval gate.

## 5. Export Review Material

```powershell
py .\consulting.py export-obsidian --project-id 1 --output-dir .local\obsidian-preview --lang bilingual
py .\consulting.py export-json-snapshot --out .local\status-snapshot.json
py .\consulting.py export-review-packet --project-id 1 --output-dir .local\review-packet-preview --obsidian-manifest .local\obsidian-preview\_manifest.json
```

The exports are local preview artifacts. They do not write to a live vault.

## 6. Exercise the Case-Study Gate

This should fail before approval:

```powershell
py .\consulting.py export-case-study --project-id 1 --out .local\case-study-1.md --lang bilingual
```

Record approval and export:

```powershell
py .\consulting.py approve-case-study --project-id 1 --approved-by "operator"
py .\consulting.py export-case-study --project-id 1 --out .local\case-study-1.md --lang bilingual
```

Revoke approval to block future exports again:

```powershell
py .\consulting.py revoke-case-study-approval --project-id 1
```

## 7. Test

```powershell
py -m unittest discover -s tests -v
```
