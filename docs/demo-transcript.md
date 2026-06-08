# Demo Transcript

This transcript shows the public-safe demo path using the synthetic lead in
`examples/leads.csv`. Local generated files are written under `.local/`, which
is ignored by git.

The run demonstrates four boundaries:

- public status output uses `Client 1`, not raw contact identity
- generated artifacts stay local
- delivery readiness is separate from case-study approval
- case-study export is blocked until explicit approval is recorded

## Commands

```powershell
py .\consulting.py init-db --db .local\demo.sqlite
py .\consulting.py import-leads --db .local\demo.sqlite --csv .\examples\leads.csv --lang bilingual
py .\consulting.py score-leads --db .local\demo.sqlite --lang bilingual
py .\consulting.py list-leads --db .local\demo.sqlite
py .\consulting.py generate-proposal --db .local\demo.sqlite --lead-id 1 --out .local\demo\proposal-1.md --lang bilingual
py .\consulting.py record-discovery-call --db .local\demo.sqlite --lead-id 1 --project-id 1 --summary "Current workflow relies on manual handoffs." --current-state "Manual research spreadsheet" --blockers "No repeatable intake" --desired-outcome "Reusable content offer" --next-step "Send workflow map" --out .local\demo\discovery-1.md --lang bilingual
py .\consulting.py generate-delivery-report --db .local\demo.sqlite --project-id 1 --out .local\demo\report-1.md --lang bilingual
py .\consulting.py generate-delivery-checklist --db .local\demo.sqlite --project-id 1 --out .local\demo\checklist-1.md --lang bilingual
py .\consulting.py generate-followup --db .local\demo.sqlite --project-id 1 --out .local\demo\followup-1.md --lang bilingual
py .\consulting.py dashboard --db .local\demo.sqlite
py .\consulting.py validate-project --db .local\demo.sqlite --project-id 1
py .\consulting.py what-remains --db .local\demo.sqlite --project-id 1
py .\consulting.py export-review-packet --db .local\demo.sqlite --project-id 1 --output-dir .local\demo\review-packet-preview
py .\consulting.py export-case-study --db .local\demo.sqlite --project-id 1 --out .local\demo\case-study-1.md --lang bilingual
```

## Output

```text
Initialized DB / 已初始化数据库: .local\demo.sqlite
Imported leads / 已导入线索: 1
Scored leads / 已评分线索: 1

Leads / 线索
- L-0001 (Client 1) score=27 classification=1v1 consultation fit offer=workflow_sprint_3_session

Wrote proposal / 已写入提案: .local\demo\proposal-1.md
Wrote discovery call notes / 已写入访谈记录: .local\demo\discovery-1.md
Wrote delivery report / 已写入交付报告: .local\demo\report-1.md
Wrote delivery checklist / 已写入交付清单: .local\demo\checklist-1.md
Wrote follow-up plan / 已写入跟进计划: .local\demo\followup-1.md
```

## Readiness

```text
Dashboard / 仪表盘
- leads=1
- projects=1
- case_study_approved=0
- followups: done=0 planned=3
- delivery_checklist: done=0 pending=7

Project validation / 项目检查: project 1 (Client 1)
- proposal: ok
- delivery_report: ok
- delivery_checklist: ok count=7 done=0 pending=7
- followups: ok count=3 done=0 planned=3
- case_study_approved=false
- ready_for_delivery=true

What remains / 剩余任务: project 1 (Client 1)
- ready_for_delivery=true
- case_study_approved=false
- No required delivery artifacts are missing.
- Optional gate: approve-case-study before exporting a case study.
```

## Review Packet And Case-Study Gate

```text
Wrote review packet / 已写入审核包:
- .local\demo\review-packet-preview\review-packet-project-1.md
- .local\demo\review-packet-preview\_review_packet_manifest.json

Blocked: client_approved_for_case_study is false / 已阻止：客户尚未批准案例
```

The final command exits non-zero by design. To export a case-study draft, record
approval first with `approve-case-study`; use `revoke-case-study-approval` to
block future exports again.
