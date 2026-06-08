# Portfolio Case Study

## Problem

Small consulting pilots often begin with a lightweight form, a spreadsheet, a
few notes, and manual follow-up reminders. That is enough to start work, but it
does not create a repeatable delivery trail or a clean review packet.

The risk is not only operational drift. If client facts move straight from raw
intake into public notes, the case-study process can leak identity or imply
approval that was never given.

## Solution

Consulting CRM Lite keeps the consulting loop local and explicit:

1. Import a lead from CSV.
2. Score fit and recommend an offer.
3. Generate a proposal and delivery artifacts.
4. Track delivery checklist and follow-up status.
5. Export a local review packet.
6. Require explicit approval before exporting a case-study draft.

## Design Choices

- Local SQLite instead of a hosted CRM.
- Deterministic scoring instead of a black-box model call.
- Anonymized aliases in public/status output.
- Preview-only exports for Obsidian-style notes.
- JSON views for automation handoffs.
- Approval and revocation commands for case-study control.

## Result

The repo demonstrates a practical AI workflow consulting operating loop without
requiring credentials, paid APIs, or real customer records. It is small enough
to audit and complete enough to run end to end from a terminal.
