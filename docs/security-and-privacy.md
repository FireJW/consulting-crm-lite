# Security and Privacy Notes

Consulting CRM Lite is a local-first demo tool, not a hosted security product.
Its safety model is intentionally simple and inspectable.

## Data Boundary

- The CLI uses local files only.
- The default database is `.local\consulting-crm.sqlite`.
- `.local/` is ignored by git.
- There are no external API calls.
- There is no account connection or browser automation.
- The tool does not send email, messages, posts, or notifications.

## PII Handling

CSV imports may include contact fields such as name, email, and company. The CLI
uses those fields to compute a short local hash for duplicate detection, then
renders public/status output through an anonymized alias such as `Client 1`.

Generated status views, review packets, JSON snapshots, Obsidian previews, and
case-study exports are designed to avoid raw contact details by default.

## Preview-Only Vault Exports

`export-obsidian` refuses output directories unless the path looks local or
preview-only. Allowed examples include:

```text
.local\obsidian-preview
.tmp\obsidian-preview
tmp\obsidian-preview
```

The manifest written by the export includes:

```json
{
  "pii_status": "anonymized",
  "live_vault_write": false
}
```

## Case-Study Approval Gate

`export-case-study` exits non-zero until `client_approved_for_case_study=true`
is recorded for the project.

Approval can also be revoked:

```powershell
py .\consulting.py revoke-case-study-approval --project-id 1
```

After revocation, future case-study exports are blocked again.

## Public Demo Data

The sample CSV is synthetic and intentionally uses a non-routable
`example.invalid` email address. Replace it with private data only in local,
ignored working folders.
