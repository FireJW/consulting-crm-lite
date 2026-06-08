import csv
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "consulting.py"


class ConsultingCliTest(unittest.TestCase):
    def run_cli(self, *args, cwd=None, check=True):
        result = subprocess.run(
            [sys.executable, str(CLI), *args],
            cwd=cwd or ROOT,
            text=True,
            capture_output=True,
        )
        if check and result.returncode != 0:
            self.fail(f"command failed: {result.stderr}\nstdout:\n{result.stdout}")
        return result

    def write_leads_csv(self, path):
        rows = [
            {
                "name": "Sample Founder",
                "email": "sample-founder@example.invalid",
                "company": "Sample Studio",
                "role": "Founder",
                "current_workflow": "Manual content planning in docs",
                "pain_points": "Wasting time every week; no reusable workflow",
                "ai_tools": "ChatGPT, Claude",
                "desired_outcome": "A repeatable AI product workflow",
                "budget_range": "1000-3000",
                "time_urgency": "this_week",
                "source": "tally",
            }
        ]
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    def test_import_scores_and_anonymizes_lead(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db = tmp / "consulting.sqlite"
            leads_csv = tmp / "leads.csv"
            self.write_leads_csv(leads_csv)

            self.run_cli("init-db", "--db", str(db))
            self.run_cli("import-leads", "--db", str(db), "--csv", str(leads_csv), "--lang", "bilingual")
            self.run_cli("score-leads", "--db", str(db), "--lang", "bilingual")

            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            lead = conn.execute("select * from leads").fetchone()
            score = conn.execute("select * from lead_scores").fetchone()

            self.assertEqual(lead["lead_code"], "L-0001")
            self.assertEqual(lead["client_alias"], "Client 1")
            self.assertNotIn("Sample Founder", lead["anonymized_profile_json"])
            self.assertNotIn("sample-founder@example.invalid", lead["anonymized_profile_json"])
            self.assertGreaterEqual(score["total_score"], 20)
            self.assertIn(score["classification"], {"1v1 consultation fit", "team consulting fit"})
            conn.close()

    def test_generates_bilingual_proposal_and_report(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db = tmp / "consulting.sqlite"
            leads_csv = tmp / "leads.csv"
            proposal = tmp / "proposal.md"
            report = tmp / "report.md"
            self.write_leads_csv(leads_csv)

            self.run_cli("init-db", "--db", str(db))
            self.run_cli("import-leads", "--db", str(db), "--csv", str(leads_csv))
            self.run_cli("score-leads", "--db", str(db))
            self.run_cli("generate-proposal", "--db", str(db), "--lead-id", "1", "--out", str(proposal), "--lang", "bilingual")
            self.run_cli("generate-delivery-report", "--db", str(db), "--project-id", "1", "--out", str(report), "--lang", "bilingual")

            proposal_text = proposal.read_text(encoding="utf-8")
            report_text = report.read_text(encoding="utf-8")
            self.assertIn("Consulting Proposal / 咨询提案", proposal_text)
            self.assertIn("Recommended offer / 推荐服务包", proposal_text)
            self.assertIn("Delivery Report / 交付报告", report_text)
            self.assertIn("Follow-up plan / 跟进计划", report_text)

    def test_generated_markdown_uses_readable_chinese_labels(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db = tmp / "consulting.sqlite"
            leads_csv = tmp / "leads.csv"
            proposal = tmp / "proposal.md"
            report = tmp / "report.md"
            followup = tmp / "followup.md"
            case_study = tmp / "case-study.md"
            preview_dir = tmp / "obsidian-preview"
            self.write_leads_csv(leads_csv)

            self.run_cli("init-db", "--db", str(db))
            self.run_cli("import-leads", "--db", str(db), "--csv", str(leads_csv))
            self.run_cli("score-leads", "--db", str(db))
            self.run_cli("generate-proposal", "--db", str(db), "--lead-id", "1", "--out", str(proposal), "--lang", "bilingual")
            self.run_cli("generate-delivery-report", "--db", str(db), "--project-id", "1", "--out", str(report), "--lang", "bilingual")
            self.run_cli("generate-followup", "--db", str(db), "--project-id", "1", "--out", str(followup), "--lang", "bilingual")
            self.run_cli("approve-case-study", "--db", str(db), "--project-id", "1", "--approved-by", "test")
            self.run_cli("export-case-study", "--db", str(db), "--project-id", "1", "--out", str(case_study), "--lang", "bilingual")
            self.run_cli("export-obsidian", "--db", str(db), "--project-id", "1", "--output-dir", str(preview_dir), "--lang", "bilingual")

            combined = "\n".join(
                [
                    proposal.read_text(encoding="utf-8"),
                    report.read_text(encoding="utf-8"),
                    followup.read_text(encoding="utf-8"),
                    case_study.read_text(encoding="utf-8"),
                    (preview_dir / "consulting-project-1.md").read_text(encoding="utf-8"),
                ]
            )
            self.assertIn("Consulting Proposal / 咨询提案", combined)
            self.assertIn("Recommended offer / 推荐服务包", combined)
            self.assertIn("Delivery Report / 交付报告", combined)
            self.assertIn("Follow-up Plan / 跟进计划", combined)
            self.assertIn("Case Study Draft / 案例草稿", combined)
            self.assertIn("Consulting Delivery Preview / 咨询交付预览", combined)
            for mojibake in ("鍜", "浜", "璺", "鏈", "鑽", "€"):
                self.assertNotIn(mojibake, combined)

    def test_case_study_export_requires_approval(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db = tmp / "consulting.sqlite"
            leads_csv = tmp / "leads.csv"
            case_study = tmp / "case-study.md"
            self.write_leads_csv(leads_csv)

            self.run_cli("init-db", "--db", str(db))
            self.run_cli("import-leads", "--db", str(db), "--csv", str(leads_csv))
            self.run_cli("score-leads", "--db", str(db))
            self.run_cli("generate-proposal", "--db", str(db), "--lead-id", "1", "--out", str(tmp / "proposal.md"))

            blocked = self.run_cli(
                "export-case-study",
                "--db",
                str(db),
                "--project-id",
                "1",
                "--out",
                str(case_study),
                check=False,
            )
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("client_approved_for_case_study", blocked.stderr)
            self.assertFalse(case_study.exists())

            self.run_cli("approve-case-study", "--db", str(db), "--project-id", "1", "--approved-by", "test")
            self.run_cli("export-case-study", "--db", str(db), "--project-id", "1", "--out", str(case_study), "--lang", "bilingual")
            text = case_study.read_text(encoding="utf-8")
            self.assertIn("Case Study Draft / 案例草稿", text)
            self.assertNotIn("Alice", text)
            self.assertNotIn("alice@example.com", text)

    def test_revoke_case_study_approval_blocks_future_export(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db = tmp / "consulting.sqlite"
            leads_csv = tmp / "leads.csv"
            first_case_study = tmp / "case-study-approved.md"
            revoked_case_study = tmp / "case-study-revoked.md"
            self.write_leads_csv(leads_csv)

            self.run_cli("init-db", "--db", str(db))
            self.run_cli("import-leads", "--db", str(db), "--csv", str(leads_csv))
            self.run_cli("score-leads", "--db", str(db))
            self.run_cli("generate-proposal", "--db", str(db), "--lead-id", "1", "--out", str(tmp / "proposal.md"))
            self.run_cli("approve-case-study", "--db", str(db), "--project-id", "1", "--approved-by", "test")
            self.run_cli(
                "export-case-study",
                "--db",
                str(db),
                "--project-id",
                "1",
                "--out",
                str(first_case_study),
            )

            self.run_cli("revoke-case-study-approval", "--db", str(db), "--project-id", "1")

            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            project = conn.execute(
                "select client_approved_for_case_study, approval_snapshot_json from delivery_projects where id = 1"
            ).fetchone()
            conn.close()
            self.assertEqual(project["client_approved_for_case_study"], 0)
            self.assertEqual(project["approval_snapshot_json"], "{}")

            blocked = self.run_cli(
                "export-case-study",
                "--db",
                str(db),
                "--project-id",
                "1",
                "--out",
                str(revoked_case_study),
                check=False,
            )
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("client_approved_for_case_study", blocked.stderr)
            self.assertFalse(revoked_case_study.exists())

    def test_case_study_approval_commands_can_print_json_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db = tmp / "consulting.sqlite"
            leads_csv = tmp / "leads.csv"
            self.write_leads_csv(leads_csv)

            self.run_cli("init-db", "--db", str(db))
            self.run_cli("import-leads", "--db", str(db), "--csv", str(leads_csv))
            self.run_cli("score-leads", "--db", str(db))
            self.run_cli("generate-proposal", "--db", str(db), "--lead-id", "1", "--out", str(tmp / "proposal.md"))

            approved = self.run_cli(
                "approve-case-study",
                "--db",
                str(db),
                "--project-id",
                "1",
                "--approved-by",
                "test",
                "--format",
                "json",
            )
            approved_payload = json.loads(approved.stdout)
            self.assertEqual(approved_payload["kind"], "case_study_approval")
            self.assertEqual(approved_payload["project_id"], 1)
            self.assertEqual(approved_payload["client_alias"], "Client 1")
            self.assertTrue(approved_payload["case_study_approved"])
            self.assertEqual(approved_payload["approval_snapshot"]["approved_by"], "test")
            self.assertEqual(approved_payload["approval_snapshot"]["approval_mode"], "manual_local")
            self.assertNotIn("Alice", approved.stdout)
            self.assertNotIn("alice@example.com", approved.stdout)

            revoked = self.run_cli(
                "revoke-case-study-approval",
                "--db",
                str(db),
                "--project-id",
                "1",
                "--format",
                "json",
            )
            revoked_payload = json.loads(revoked.stdout)
            self.assertEqual(revoked_payload["kind"], "case_study_approval")
            self.assertEqual(revoked_payload["project_id"], 1)
            self.assertEqual(revoked_payload["client_alias"], "Client 1")
            self.assertFalse(revoked_payload["case_study_approved"])
            self.assertEqual(revoked_payload["approval_snapshot"], {})
            self.assertNotIn("Alice", revoked.stdout)
            self.assertNotIn("alice@example.com", revoked.stdout)

    def test_export_case_study_can_print_json_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db = tmp / "consulting.sqlite"
            leads_csv = tmp / "leads.csv"
            case_study = tmp / "case-study.md"
            self.write_leads_csv(leads_csv)

            self.run_cli("init-db", "--db", str(db))
            self.run_cli("import-leads", "--db", str(db), "--csv", str(leads_csv))
            self.run_cli("score-leads", "--db", str(db))
            self.run_cli("generate-proposal", "--db", str(db), "--lead-id", "1", "--out", str(tmp / "proposal.md"))
            self.run_cli("approve-case-study", "--db", str(db), "--project-id", "1", "--approved-by", "test")

            result = self.run_cli(
                "export-case-study",
                "--db",
                str(db),
                "--project-id",
                "1",
                "--out",
                str(case_study),
                "--format",
                "json",
            )

            payload = json.loads(result.stdout)
            self.assertEqual(payload["kind"], "case_study_export")
            self.assertEqual(payload["project_id"], 1)
            self.assertEqual(payload["lead_code"], "L-0001")
            self.assertEqual(payload["client_alias"], "Client 1")
            self.assertEqual(payload["status"], "draft")
            self.assertEqual(payload["output_path"], str(case_study))
            self.assertGreater(payload["case_study_id"], 0)
            self.assertGreater(payload["draft_char_count"], 0)
            self.assertNotIn("draft_markdown", payload)
            self.assertTrue(case_study.exists())
            self.assertNotIn("Alice", result.stdout)
            self.assertNotIn("alice@example.com", result.stdout)

    def test_export_obsidian_writes_preview_only_anonymized_notes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db = tmp / "consulting.sqlite"
            leads_csv = tmp / "leads.csv"
            preview_dir = tmp / "obsidian-preview"
            self.write_leads_csv(leads_csv)

            self.run_cli("init-db", "--db", str(db))
            self.run_cli("import-leads", "--db", str(db), "--csv", str(leads_csv))
            self.run_cli("score-leads", "--db", str(db))
            self.run_cli("generate-proposal", "--db", str(db), "--lead-id", "1", "--out", str(tmp / "proposal.md"))
            self.run_cli("generate-delivery-report", "--db", str(db), "--project-id", "1", "--out", str(tmp / "report.md"))
            self.run_cli("export-obsidian", "--db", str(db), "--project-id", "1", "--output-dir", str(preview_dir), "--lang", "bilingual")

            files = sorted(path.name for path in preview_dir.glob("*.md"))
            self.assertEqual(files, ["consulting-lead-L-0001.md", "consulting-project-1.md"])
            lead_note = (preview_dir / "consulting-lead-L-0001.md").read_text(encoding="utf-8")
            project_note = (preview_dir / "consulting-project-1.md").read_text(encoding="utf-8")
            self.assertIn("kb_type: consulting_delivery", lead_note)
            self.assertIn("consulting_type: lead", lead_note)
            self.assertIn("pii_status: anonymized", lead_note)
            self.assertIn("case_study_approved: false", project_note)
            self.assertIn("Consulting Delivery Preview / 咨询交付预览", project_note)
            self.assertNotIn("Alice", lead_note + project_note)
            self.assertNotIn("alice@example.com", lead_note + project_note)

            manifest = json.loads((preview_dir / "_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["kind"], "obsidian_preview_manifest")
            self.assertEqual(manifest["project_id"], 1)
            self.assertEqual(manifest["lead_code"], "L-0001")
            self.assertEqual(manifest["pii_status"], "anonymized")
            self.assertFalse(manifest["live_vault_write"])
            self.assertEqual(
                sorted(item["filename"] for item in manifest["files"]),
                ["consulting-lead-L-0001.md", "consulting-project-1.md"],
            )

    def test_export_obsidian_rejects_non_preview_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db = tmp / "consulting.sqlite"
            leads_csv = tmp / "leads.csv"
            live_like = Path(tmpdir).parent / "Private Workspace"
            self.write_leads_csv(leads_csv)

            self.run_cli("init-db", "--db", str(db))
            self.run_cli("import-leads", "--db", str(db), "--csv", str(leads_csv))
            self.run_cli("score-leads", "--db", str(db))
            self.run_cli("generate-proposal", "--db", str(db), "--lead-id", "1", "--out", str(tmp / "proposal.md"))

            result = self.run_cli(
                "export-obsidian",
                "--db",
                str(db),
                "--project-id",
                "1",
                "--output-dir",
                str(live_like),
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("preview", result.stderr.lower())

    def test_generate_followup_writes_plan_and_records(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db = tmp / "consulting.sqlite"
            leads_csv = tmp / "leads.csv"
            followup = tmp / "followup.md"
            self.write_leads_csv(leads_csv)

            self.run_cli("init-db", "--db", str(db))
            self.run_cli("import-leads", "--db", str(db), "--csv", str(leads_csv))
            self.run_cli("score-leads", "--db", str(db))
            self.run_cli("generate-proposal", "--db", str(db), "--lead-id", "1", "--out", str(tmp / "proposal.md"))
            self.run_cli("generate-followup", "--db", str(db), "--project-id", "1", "--out", str(followup), "--lang", "bilingual")

            text = followup.read_text(encoding="utf-8")
            self.assertIn("Follow-up Plan / 跟进计划", text)
            self.assertIn("48 hours", text)
            self.assertIn("7 days", text)
            self.assertIn("30 days", text)
            self.assertNotIn("Alice", text)
            self.assertNotIn("alice@example.com", text)

            conn = sqlite3.connect(db)
            count = conn.execute("select count(*) from followups where project_id = 1").fetchone()[0]
            conn.close()
            self.assertEqual(count, 3)

    def test_record_discovery_call_writes_anonymized_note_and_record(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db = tmp / "consulting.sqlite"
            leads_csv = tmp / "leads.csv"
            discovery = tmp / "discovery.md"
            self.write_leads_csv(leads_csv)

            self.run_cli("init-db", "--db", str(db))
            self.run_cli("import-leads", "--db", str(db), "--csv", str(leads_csv))
            self.run_cli(
                "record-discovery-call",
                "--db",
                str(db),
                "--lead-id",
                "1",
                "--summary",
                "Current workflow relies on manual handoffs.",
                "--out",
                str(discovery),
                "--lang",
                "bilingual",
            )

            text = discovery.read_text(encoding="utf-8")
            self.assertIn("Discovery Call Notes", text)
            self.assertIn("Client 1", text)
            self.assertIn("Current workflow relies on manual handoffs.", text)
            self.assertNotIn("Alice", text)
            self.assertNotIn("alice@example.com", text)

            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            row = conn.execute("select * from discovery_calls where lead_id = 1").fetchone()
            conn.close()
            self.assertIsNotNone(row)
            self.assertIn("manual handoffs", row["summary"])

    def test_record_discovery_call_accepts_structured_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db = tmp / "consulting.sqlite"
            leads_csv = tmp / "leads.csv"
            discovery = tmp / "discovery.md"
            self.write_leads_csv(leads_csv)

            self.run_cli("init-db", "--db", str(db))
            self.run_cli("import-leads", "--db", str(db), "--csv", str(leads_csv))
            self.run_cli(
                "record-discovery-call",
                "--db",
                str(db),
                "--lead-id",
                "1",
                "--summary",
                "Current workflow relies on manual handoffs.",
                "--current-state",
                "Manual research spreadsheet",
                "--blockers",
                "No repeatable intake",
                "--desired-outcome",
                "Reusable content offer",
                "--next-step",
                "Send workflow map",
                "--out",
                str(discovery),
            )

            text = discovery.read_text(encoding="utf-8")
            self.assertIn("## Structured Fields / 结构化字段", text)
            self.assertIn("Current state / 现状: Manual research spreadsheet", text)
            self.assertIn("Blockers / 阻塞点: No repeatable intake", text)
            self.assertIn("Desired outcome / 目标结果: Reusable content offer", text)
            self.assertIn("Next step / 下一步: Send workflow map", text)
            self.assertNotIn("Alice", text)
            self.assertNotIn("alice@example.com", text)

            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            row = conn.execute("select * from discovery_calls where lead_id = 1").fetchone()
            conn.close()
            self.assertEqual(row["current_state"], "Manual research spreadsheet")
            self.assertEqual(row["blockers"], "No repeatable intake")
            self.assertEqual(row["desired_outcome"], "Reusable content offer")
            self.assertEqual(row["next_step"], "Send workflow map")

    def test_generate_delivery_checklist_writes_structured_items_and_records(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db = tmp / "consulting.sqlite"
            leads_csv = tmp / "leads.csv"
            checklist = tmp / "checklist.md"
            self.write_leads_csv(leads_csv)

            self.run_cli("init-db", "--db", str(db))
            self.run_cli("import-leads", "--db", str(db), "--csv", str(leads_csv))
            self.run_cli("score-leads", "--db", str(db))
            self.run_cli("generate-proposal", "--db", str(db), "--lead-id", "1", "--out", str(tmp / "proposal.md"))
            self.run_cli(
                "generate-delivery-checklist",
                "--db",
                str(db),
                "--project-id",
                "1",
                "--out",
                str(checklist),
                "--lang",
                "bilingual",
            )

            text = checklist.read_text(encoding="utf-8")
            self.assertIn("Delivery Checklist", text)
            self.assertIn("agenda", text.lower())
            self.assertIn("workflow map", text.lower())
            self.assertNotIn("Alice", text)
            self.assertNotIn("alice@example.com", text)

            conn = sqlite3.connect(db)
            rows = conn.execute(
                "select item_key, status from delivery_checklists where project_id = 1 order by id"
            ).fetchall()
            conn.close()
            self.assertGreaterEqual(len(rows), 5)
            self.assertTrue(all(row[1] == "pending" for row in rows))

    def test_list_delivery_checklist_prints_anonymized_project_items(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db = tmp / "consulting.sqlite"
            leads_csv = tmp / "leads.csv"
            self.write_leads_csv(leads_csv)

            self.run_cli("init-db", "--db", str(db))
            self.run_cli("import-leads", "--db", str(db), "--csv", str(leads_csv))
            self.run_cli("score-leads", "--db", str(db))
            self.run_cli("generate-proposal", "--db", str(db), "--lead-id", "1", "--out", str(tmp / "proposal.md"))
            self.run_cli("generate-delivery-checklist", "--db", str(db), "--project-id", "1", "--out", str(tmp / "checklist.md"))

            result = self.run_cli("list-delivery-checklist", "--db", str(db), "--project-id", "1")

            self.assertIn("Client 1", result.stdout)
            self.assertIn("Agenda", result.stdout)
            self.assertIn("Workflow map", result.stdout)
            self.assertIn("pending", result.stdout)
            self.assertNotIn("Alice", result.stdout)
            self.assertNotIn("alice@example.com", result.stdout)

    def test_list_delivery_checklist_can_print_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db = tmp / "consulting.sqlite"
            leads_csv = tmp / "leads.csv"
            self.write_leads_csv(leads_csv)

            self.run_cli("init-db", "--db", str(db))
            self.run_cli("import-leads", "--db", str(db), "--csv", str(leads_csv))
            self.run_cli("score-leads", "--db", str(db))
            self.run_cli("generate-proposal", "--db", str(db), "--lead-id", "1", "--out", str(tmp / "proposal.md"))
            self.run_cli("generate-delivery-checklist", "--db", str(db), "--project-id", "1", "--out", str(tmp / "checklist.md"))
            self.run_cli("mark-checklist-done", "--db", str(db), "--checklist-id", "1", "--note", "Reviewed")

            result = self.run_cli("list-delivery-checklist", "--db", str(db), "--project-id", "1", "--format", "json")

            payload = json.loads(result.stdout)
            self.assertEqual(payload["kind"], "delivery_checklist")
            self.assertEqual(payload["project_id"], 1)
            self.assertEqual(payload["client_alias"], "Client 1")
            self.assertEqual(len(payload["items"]), 7)
            self.assertEqual(payload["items"][0]["status"], "done")
            self.assertEqual(payload["items"][0]["completion_note"], "Reviewed")
            self.assertEqual(payload["items"][1]["status"], "pending")
            self.assertNotIn("Alice", result.stdout)
            self.assertNotIn("alice@example.com", result.stdout)

    def test_mark_checklist_done_updates_one_delivery_item(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db = tmp / "consulting.sqlite"
            leads_csv = tmp / "leads.csv"
            self.write_leads_csv(leads_csv)

            self.run_cli("init-db", "--db", str(db))
            self.run_cli("import-leads", "--db", str(db), "--csv", str(leads_csv))
            self.run_cli("score-leads", "--db", str(db))
            self.run_cli("generate-proposal", "--db", str(db), "--lead-id", "1", "--out", str(tmp / "proposal.md"))
            self.run_cli("generate-delivery-checklist", "--db", str(db), "--project-id", "1", "--out", str(tmp / "checklist.md"))
            self.run_cli("mark-checklist-done", "--db", str(db), "--checklist-id", "1")

            conn = sqlite3.connect(db)
            statuses = conn.execute("select status from delivery_checklists order by id").fetchall()
            conn.close()
            self.assertEqual(statuses[0][0], "done")
            self.assertEqual(statuses[1][0], "pending")

    def test_mark_checklist_done_records_note_and_reopen_clears_completion(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db = tmp / "consulting.sqlite"
            leads_csv = tmp / "leads.csv"
            self.write_leads_csv(leads_csv)

            self.run_cli("init-db", "--db", str(db))
            self.run_cli("import-leads", "--db", str(db), "--csv", str(leads_csv))
            self.run_cli("score-leads", "--db", str(db))
            self.run_cli("generate-proposal", "--db", str(db), "--lead-id", "1", "--out", str(tmp / "proposal.md"))
            self.run_cli("generate-delivery-checklist", "--db", str(db), "--project-id", "1", "--out", str(tmp / "checklist.md"))
            self.run_cli("mark-checklist-done", "--db", str(db), "--checklist-id", "1", "--note", "Reviewed with client")

            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            done = conn.execute("select status, completion_note, completed_at from delivery_checklists where id = 1").fetchone()
            conn.close()
            self.assertEqual(done["status"], "done")
            self.assertEqual(done["completion_note"], "Reviewed with client")
            self.assertTrue(done["completed_at"])

            self.run_cli("reopen-checklist-item", "--db", str(db), "--checklist-id", "1")

            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            reopened = conn.execute("select status, completion_note, completed_at from delivery_checklists where id = 1").fetchone()
            conn.close()
            self.assertEqual(reopened["status"], "pending")
            self.assertEqual(reopened["completion_note"], "")
            self.assertEqual(reopened["completed_at"], "")

    def test_list_followups_prints_anonymized_project_queue(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db = tmp / "consulting.sqlite"
            leads_csv = tmp / "leads.csv"
            self.write_leads_csv(leads_csv)

            self.run_cli("init-db", "--db", str(db))
            self.run_cli("import-leads", "--db", str(db), "--csv", str(leads_csv))
            self.run_cli("score-leads", "--db", str(db))
            self.run_cli("generate-proposal", "--db", str(db), "--lead-id", "1", "--out", str(tmp / "proposal.md"))
            self.run_cli("generate-followup", "--db", str(db), "--project-id", "1", "--out", str(tmp / "followup.md"))

            result = self.run_cli("list-followups", "--db", str(db), "--project-id", "1")

            self.assertIn("Client 1", result.stdout)
            self.assertIn("48 hours", result.stdout)
            self.assertIn("delivery_summary", result.stdout)
            self.assertIn("planned", result.stdout)
            self.assertNotIn("Alice", result.stdout)
            self.assertNotIn("alice@example.com", result.stdout)

    def test_list_followups_can_print_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db = tmp / "consulting.sqlite"
            leads_csv = tmp / "leads.csv"
            self.write_leads_csv(leads_csv)

            self.run_cli("init-db", "--db", str(db))
            self.run_cli("import-leads", "--db", str(db), "--csv", str(leads_csv))
            self.run_cli("score-leads", "--db", str(db))
            self.run_cli("generate-proposal", "--db", str(db), "--lead-id", "1", "--out", str(tmp / "proposal.md"))
            self.run_cli("generate-followup", "--db", str(db), "--project-id", "1", "--out", str(tmp / "followup.md"))
            self.run_cli("mark-followup-done", "--db", str(db), "--followup-id", "1", "--note", "Confirmed")

            result = self.run_cli("list-followups", "--db", str(db), "--project-id", "1", "--format", "json")

            payload = json.loads(result.stdout)
            self.assertEqual(payload["kind"], "followup_queue")
            self.assertEqual(payload["project_id"], 1)
            self.assertEqual(payload["client_alias"], "Client 1")
            self.assertEqual(len(payload["followups"]), 3)
            self.assertEqual(payload["followups"][0]["status"], "done")
            self.assertEqual(payload["followups"][0]["completion_note"], "Confirmed")
            self.assertEqual(payload["followups"][1]["status"], "planned")
            self.assertNotIn("Alice", result.stdout)
            self.assertNotIn("alice@example.com", result.stdout)

    def test_mark_followup_done_updates_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db = tmp / "consulting.sqlite"
            leads_csv = tmp / "leads.csv"
            self.write_leads_csv(leads_csv)

            self.run_cli("init-db", "--db", str(db))
            self.run_cli("import-leads", "--db", str(db), "--csv", str(leads_csv))
            self.run_cli("score-leads", "--db", str(db))
            self.run_cli("generate-proposal", "--db", str(db), "--lead-id", "1", "--out", str(tmp / "proposal.md"))
            self.run_cli("generate-followup", "--db", str(db), "--project-id", "1", "--out", str(tmp / "followup.md"))
            self.run_cli("mark-followup-done", "--db", str(db), "--followup-id", "1")

            conn = sqlite3.connect(db)
            statuses = conn.execute("select status from followups order by id").fetchall()
            conn.close()
            self.assertEqual(statuses[0][0], "done")
            self.assertEqual(statuses[1][0], "planned")

    def test_mark_followup_done_records_note_and_reopen_clears_completion(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db = tmp / "consulting.sqlite"
            leads_csv = tmp / "leads.csv"
            self.write_leads_csv(leads_csv)

            self.run_cli("init-db", "--db", str(db))
            self.run_cli("import-leads", "--db", str(db), "--csv", str(leads_csv))
            self.run_cli("score-leads", "--db", str(db))
            self.run_cli("generate-proposal", "--db", str(db), "--lead-id", "1", "--out", str(tmp / "proposal.md"))
            self.run_cli("generate-followup", "--db", str(db), "--project-id", "1", "--out", str(tmp / "followup.md"))
            self.run_cli("mark-followup-done", "--db", str(db), "--followup-id", "1", "--note", "Client confirmed summary")

            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            done = conn.execute("select status, completion_note, completed_at from followups where id = 1").fetchone()
            conn.close()
            self.assertEqual(done["status"], "done")
            self.assertEqual(done["completion_note"], "Client confirmed summary")
            self.assertTrue(done["completed_at"])

            self.run_cli("reopen-followup", "--db", str(db), "--followup-id", "1")

            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            reopened = conn.execute("select status, completion_note, completed_at from followups where id = 1").fetchone()
            conn.close()
            self.assertEqual(reopened["status"], "planned")
            self.assertEqual(reopened["completion_note"], "")
            self.assertEqual(reopened["completed_at"], "")

    def test_list_leads_prints_anonymized_scores(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db = tmp / "consulting.sqlite"
            leads_csv = tmp / "leads.csv"
            self.write_leads_csv(leads_csv)

            self.run_cli("init-db", "--db", str(db))
            self.run_cli("import-leads", "--db", str(db), "--csv", str(leads_csv))
            self.run_cli("score-leads", "--db", str(db))

            result = self.run_cli("list-leads", "--db", str(db))

            self.assertIn("L-0001", result.stdout)
            self.assertIn("Client 1", result.stdout)
            self.assertIn("1v1 consultation fit", result.stdout)
            self.assertIn("workflow_sprint_3_session", result.stdout)
            self.assertNotIn("Alice", result.stdout)
            self.assertNotIn("alice@example.com", result.stdout)

    def test_list_leads_can_print_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db = tmp / "consulting.sqlite"
            leads_csv = tmp / "leads.csv"
            self.write_leads_csv(leads_csv)

            self.run_cli("init-db", "--db", str(db))
            self.run_cli("import-leads", "--db", str(db), "--csv", str(leads_csv))
            self.run_cli("score-leads", "--db", str(db))

            result = self.run_cli("list-leads", "--db", str(db), "--format", "json")

            payload = json.loads(result.stdout)
            self.assertEqual(payload["kind"], "lead_list")
            self.assertEqual(len(payload["leads"]), 1)
            self.assertEqual(payload["leads"][0]["lead_code"], "L-0001")
            self.assertEqual(payload["leads"][0]["client_alias"], "Client 1")
            self.assertEqual(payload["leads"][0]["classification"], "1v1 consultation fit")
            self.assertEqual(payload["leads"][0]["recommended_offer"], "workflow_sprint_3_session")
            self.assertNotIn("Alice", result.stdout)
            self.assertNotIn("alice@example.com", result.stdout)

    def test_project_queries_print_anonymized_project_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db = tmp / "consulting.sqlite"
            leads_csv = tmp / "leads.csv"
            self.write_leads_csv(leads_csv)

            self.run_cli("init-db", "--db", str(db))
            self.run_cli("import-leads", "--db", str(db), "--csv", str(leads_csv))
            self.run_cli("score-leads", "--db", str(db))
            self.run_cli("generate-proposal", "--db", str(db), "--lead-id", "1", "--out", str(tmp / "proposal.md"))
            self.run_cli("generate-followup", "--db", str(db), "--project-id", "1", "--out", str(tmp / "followup.md"))
            self.run_cli("mark-followup-done", "--db", str(db), "--followup-id", "1")

            listed = self.run_cli("list-projects", "--db", str(db))
            shown = self.run_cli("show-project", "--db", str(db), "--project-id", "1")

            self.assertIn("project 1", listed.stdout.lower())
            self.assertIn("Client 1", listed.stdout)
            self.assertIn("workflow_sprint_3_session", listed.stdout)
            self.assertIn("case_study_approved=false", listed.stdout)
            self.assertIn("Follow-ups", shown.stdout)
            self.assertIn("done=1", shown.stdout)
            self.assertIn("planned=2", shown.stdout)
            self.assertNotIn("Alice", listed.stdout + shown.stdout)
            self.assertNotIn("alice@example.com", listed.stdout + shown.stdout)

    def test_project_queries_can_print_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db = tmp / "consulting.sqlite"
            leads_csv = tmp / "leads.csv"
            self.write_leads_csv(leads_csv)

            self.run_cli("init-db", "--db", str(db))
            self.run_cli("import-leads", "--db", str(db), "--csv", str(leads_csv))
            self.run_cli("score-leads", "--db", str(db))
            self.run_cli("generate-proposal", "--db", str(db), "--lead-id", "1", "--out", str(tmp / "proposal.md"))
            self.run_cli("generate-followup", "--db", str(db), "--project-id", "1", "--out", str(tmp / "followup.md"))
            self.run_cli("mark-followup-done", "--db", str(db), "--followup-id", "1")

            listed = self.run_cli("list-projects", "--db", str(db), "--format", "json")
            shown = self.run_cli("show-project", "--db", str(db), "--project-id", "1", "--format", "json")

            list_payload = json.loads(listed.stdout)
            show_payload = json.loads(shown.stdout)
            self.assertEqual(list_payload["kind"], "project_list")
            self.assertEqual(len(list_payload["projects"]), 1)
            self.assertEqual(list_payload["projects"][0]["project_id"], 1)
            self.assertEqual(list_payload["projects"][0]["client_alias"], "Client 1")
            self.assertEqual(list_payload["projects"][0]["offer_code"], "workflow_sprint_3_session")
            self.assertFalse(list_payload["projects"][0]["case_study_approved"])
            self.assertEqual(show_payload["kind"], "project")
            self.assertEqual(show_payload["project_id"], 1)
            self.assertEqual(show_payload["lead_code"], "L-0001")
            self.assertEqual(show_payload["followups"], {"done": 1, "planned": 2})
            self.assertNotIn("Alice", listed.stdout + shown.stdout)
            self.assertNotIn("alice@example.com", listed.stdout + shown.stdout)

    def test_dashboard_prints_anonymized_status_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db = tmp / "consulting.sqlite"
            leads_csv = tmp / "leads.csv"
            self.write_leads_csv(leads_csv)

            self.run_cli("init-db", "--db", str(db))
            self.run_cli("import-leads", "--db", str(db), "--csv", str(leads_csv))
            self.run_cli("score-leads", "--db", str(db))
            self.run_cli("generate-proposal", "--db", str(db), "--lead-id", "1", "--out", str(tmp / "proposal.md"))
            self.run_cli("generate-delivery-checklist", "--db", str(db), "--project-id", "1", "--out", str(tmp / "checklist.md"))
            self.run_cli("mark-checklist-done", "--db", str(db), "--checklist-id", "1")
            self.run_cli("generate-followup", "--db", str(db), "--project-id", "1", "--out", str(tmp / "followup.md"))
            self.run_cli("mark-followup-done", "--db", str(db), "--followup-id", "1")

            result = self.run_cli("dashboard", "--db", str(db))

            self.assertIn("Dashboard", result.stdout)
            self.assertIn("leads=1", result.stdout)
            self.assertIn("projects=1", result.stdout)
            self.assertIn("case_study_approved=0", result.stdout)
            self.assertIn("followups: done=1 planned=2", result.stdout)
            self.assertIn("delivery_checklist: done=1 pending=6", result.stdout)
            self.assertNotIn("Alice", result.stdout)
            self.assertNotIn("alice@example.com", result.stdout)

    def test_dashboard_can_print_json_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db = tmp / "consulting.sqlite"
            leads_csv = tmp / "leads.csv"
            self.write_leads_csv(leads_csv)

            self.run_cli("init-db", "--db", str(db))
            self.run_cli("import-leads", "--db", str(db), "--csv", str(leads_csv))
            self.run_cli("score-leads", "--db", str(db))
            self.run_cli("generate-proposal", "--db", str(db), "--lead-id", "1", "--out", str(tmp / "proposal.md"))
            self.run_cli("generate-delivery-checklist", "--db", str(db), "--project-id", "1", "--out", str(tmp / "checklist.md"))
            self.run_cli("mark-checklist-done", "--db", str(db), "--checklist-id", "1")
            self.run_cli("generate-followup", "--db", str(db), "--project-id", "1", "--out", str(tmp / "followup.md"))
            self.run_cli("mark-followup-done", "--db", str(db), "--followup-id", "1")

            result = self.run_cli("dashboard", "--db", str(db), "--format", "json")

            payload = json.loads(result.stdout)
            self.assertEqual(payload["kind"], "dashboard")
            self.assertEqual(payload["leads"], 1)
            self.assertEqual(payload["projects"], 1)
            self.assertEqual(payload["case_study_approved"], 0)
            self.assertEqual(payload["followups"], {"done": 1, "planned": 2})
            self.assertEqual(payload["delivery_checklist"], {"done": 1, "pending": 6})
            self.assertNotIn("Alice", result.stdout)
            self.assertNotIn("alice@example.com", result.stdout)

    def test_validate_project_reports_missing_delivery_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db = tmp / "consulting.sqlite"
            leads_csv = tmp / "leads.csv"
            self.write_leads_csv(leads_csv)

            self.run_cli("init-db", "--db", str(db))
            self.run_cli("import-leads", "--db", str(db), "--csv", str(leads_csv))
            self.run_cli("score-leads", "--db", str(db))
            self.run_cli("generate-proposal", "--db", str(db), "--lead-id", "1", "--out", str(tmp / "proposal.md"))

            result = self.run_cli("validate-project", "--db", str(db), "--project-id", "1", check=False)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("ready_for_delivery=false", result.stdout)
            self.assertIn("delivery_report: missing", result.stdout)
            self.assertIn("delivery_checklist: missing", result.stdout)
            self.assertIn("followups: missing", result.stdout)
            self.assertIn("case_study_approved=false", result.stdout)
            self.assertNotIn("Alice", result.stdout)
            self.assertNotIn("alice@example.com", result.stdout)

    def test_validate_project_can_print_json_readiness(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db = tmp / "consulting.sqlite"
            leads_csv = tmp / "leads.csv"
            self.write_leads_csv(leads_csv)

            self.run_cli("init-db", "--db", str(db))
            self.run_cli("import-leads", "--db", str(db), "--csv", str(leads_csv))
            self.run_cli("score-leads", "--db", str(db))
            self.run_cli("generate-proposal", "--db", str(db), "--lead-id", "1", "--out", str(tmp / "proposal.md"))
            self.run_cli("generate-delivery-report", "--db", str(db), "--project-id", "1", "--out", str(tmp / "report.md"))
            self.run_cli("generate-delivery-checklist", "--db", str(db), "--project-id", "1", "--out", str(tmp / "checklist.md"))
            self.run_cli("generate-followup", "--db", str(db), "--project-id", "1", "--out", str(tmp / "followup.md"))

            result = self.run_cli("validate-project", "--db", str(db), "--project-id", "1", "--format", "json")

            payload = json.loads(result.stdout)
            self.assertEqual(payload["kind"], "project_validation")
            self.assertEqual(payload["project_id"], 1)
            self.assertEqual(payload["client_alias"], "Client 1")
            self.assertTrue(payload["ready_for_delivery"])
            self.assertFalse(payload["case_study_approved"])
            self.assertEqual(payload["proposal"], {"status": "ok"})
            self.assertEqual(payload["delivery_report"], {"status": "ok"})
            self.assertEqual(payload["delivery_checklist"], {"status": "ok", "count": 7, "done": 0, "pending": 7})
            self.assertEqual(payload["followups"], {"status": "ok", "count": 3, "done": 0, "planned": 3})
            self.assertNotIn("Alice", result.stdout)
            self.assertNotIn("alice@example.com", result.stdout)

    def test_validate_project_passes_when_delivery_artifacts_exist(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db = tmp / "consulting.sqlite"
            leads_csv = tmp / "leads.csv"
            self.write_leads_csv(leads_csv)

            self.run_cli("init-db", "--db", str(db))
            self.run_cli("import-leads", "--db", str(db), "--csv", str(leads_csv))
            self.run_cli("score-leads", "--db", str(db))
            self.run_cli("generate-proposal", "--db", str(db), "--lead-id", "1", "--out", str(tmp / "proposal.md"))
            self.run_cli("generate-delivery-report", "--db", str(db), "--project-id", "1", "--out", str(tmp / "report.md"))
            self.run_cli("generate-delivery-checklist", "--db", str(db), "--project-id", "1", "--out", str(tmp / "checklist.md"))
            self.run_cli("generate-followup", "--db", str(db), "--project-id", "1", "--out", str(tmp / "followup.md"))

            result = self.run_cli("validate-project", "--db", str(db), "--project-id", "1")

            self.assertIn("ready_for_delivery=true", result.stdout)
            self.assertIn("proposal: ok", result.stdout)
            self.assertIn("delivery_report: ok", result.stdout)
            self.assertIn("delivery_checklist: ok count=7", result.stdout)
            self.assertIn("followups: ok count=3", result.stdout)
            self.assertIn("case_study_approved=false", result.stdout)
            self.assertNotIn("Alice", result.stdout)
            self.assertNotIn("alice@example.com", result.stdout)

    def test_what_remains_reports_missing_next_actions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db = tmp / "consulting.sqlite"
            leads_csv = tmp / "leads.csv"
            self.write_leads_csv(leads_csv)

            self.run_cli("init-db", "--db", str(db))
            self.run_cli("import-leads", "--db", str(db), "--csv", str(leads_csv))
            self.run_cli("score-leads", "--db", str(db))
            self.run_cli("generate-proposal", "--db", str(db), "--lead-id", "1", "--out", str(tmp / "proposal.md"))

            result = self.run_cli("what-remains", "--db", str(db), "--project-id", "1", check=False)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("What remains / 剩余任务", result.stdout)
            self.assertIn("ready_for_delivery=false", result.stdout)
            self.assertIn("generate-delivery-report", result.stdout)
            self.assertIn("generate-delivery-checklist", result.stdout)
            self.assertIn("generate-followup", result.stdout)
            self.assertIn("case_study_approved=false", result.stdout)
            self.assertNotIn("Alice", result.stdout)
            self.assertNotIn("alice@example.com", result.stdout)

    def test_what_remains_can_print_json_next_actions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db = tmp / "consulting.sqlite"
            leads_csv = tmp / "leads.csv"
            self.write_leads_csv(leads_csv)

            self.run_cli("init-db", "--db", str(db))
            self.run_cli("import-leads", "--db", str(db), "--csv", str(leads_csv))
            self.run_cli("score-leads", "--db", str(db))
            self.run_cli("generate-proposal", "--db", str(db), "--lead-id", "1", "--out", str(tmp / "proposal.md"))

            result = self.run_cli(
                "what-remains",
                "--db",
                str(db),
                "--project-id",
                "1",
                "--format",
                "json",
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stderr, "", result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["kind"], "what_remains")
            self.assertEqual(payload["project_id"], 1)
            self.assertEqual(payload["client_alias"], "Client 1")
            self.assertFalse(payload["ready_for_delivery"])
            self.assertFalse(payload["case_study_approved"])
            self.assertEqual(payload["missing_artifacts"], ["delivery_report", "delivery_checklist", "followups"])
            self.assertEqual(
                payload["next_actions"],
                ["generate-delivery-report", "generate-delivery-checklist", "generate-followup"],
            )
            self.assertEqual(payload["optional_gates"], ["approve-case-study"])
            self.assertNotIn("Alice", result.stdout)
            self.assertNotIn("alice@example.com", result.stdout)

    def test_what_remains_reports_ready_project(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db = tmp / "consulting.sqlite"
            leads_csv = tmp / "leads.csv"
            self.write_leads_csv(leads_csv)

            self.run_cli("init-db", "--db", str(db))
            self.run_cli("import-leads", "--db", str(db), "--csv", str(leads_csv))
            self.run_cli("score-leads", "--db", str(db))
            self.run_cli("generate-proposal", "--db", str(db), "--lead-id", "1", "--out", str(tmp / "proposal.md"))
            self.run_cli("generate-delivery-report", "--db", str(db), "--project-id", "1", "--out", str(tmp / "report.md"))
            self.run_cli("generate-delivery-checklist", "--db", str(db), "--project-id", "1", "--out", str(tmp / "checklist.md"))
            self.run_cli("generate-followup", "--db", str(db), "--project-id", "1", "--out", str(tmp / "followup.md"))

            result = self.run_cli("what-remains", "--db", str(db), "--project-id", "1")

            self.assertIn("ready_for_delivery=true", result.stdout)
            self.assertIn("No required delivery artifacts are missing.", result.stdout)
            self.assertIn("case_study_approved=false", result.stdout)
            self.assertNotIn("Alice", result.stdout)
            self.assertNotIn("alice@example.com", result.stdout)

    def test_export_review_packet_summarizes_local_handoff_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db = tmp / "consulting.sqlite"
            leads_csv = tmp / "leads.csv"
            obsidian_dir = tmp / "obsidian-preview"
            packet_dir = tmp / "review-packet-preview"
            self.write_leads_csv(leads_csv)

            self.run_cli("init-db", "--db", str(db))
            self.run_cli("import-leads", "--db", str(db), "--csv", str(leads_csv))
            self.run_cli("score-leads", "--db", str(db))
            self.run_cli("generate-proposal", "--db", str(db), "--lead-id", "1", "--out", str(tmp / "proposal.md"))
            self.run_cli(
                "record-discovery-call",
                "--db",
                str(db),
                "--lead-id",
                "1",
                "--project-id",
                "1",
                "--summary",
                "Current workflow relies on manual handoffs.",
                "--out",
                str(tmp / "discovery.md"),
            )
            self.run_cli("generate-delivery-report", "--db", str(db), "--project-id", "1", "--out", str(tmp / "report.md"))
            self.run_cli("generate-delivery-checklist", "--db", str(db), "--project-id", "1", "--out", str(tmp / "checklist.md"))
            self.run_cli("generate-followup", "--db", str(db), "--project-id", "1", "--out", str(tmp / "followup.md"))
            self.run_cli("export-obsidian", "--db", str(db), "--project-id", "1", "--output-dir", str(obsidian_dir))

            self.run_cli(
                "export-review-packet",
                "--db",
                str(db),
                "--project-id",
                "1",
                "--output-dir",
                str(packet_dir),
                "--obsidian-manifest",
                str(obsidian_dir / "_manifest.json"),
            )

            packet = (packet_dir / "review-packet-project-1.md").read_text(encoding="utf-8")
            manifest = json.loads((packet_dir / "_review_packet_manifest.json").read_text(encoding="utf-8"))
            self.assertIn("Consulting Review Packet / 咨询审核包", packet)
            self.assertIn("proposal: ok", packet)
            self.assertIn("delivery_report: ok", packet)
            self.assertIn("discovery_calls: count=1", packet)
            self.assertIn("delivery_checklist: count=7 done=0 pending=7", packet)
            self.assertIn("followups: count=3 done=0 planned=3", packet)
            self.assertIn("obsidian_manifest: ok files=2 live_vault_write=false", packet)
            self.assertIn("ready_for_delivery=true", packet)
            self.assertNotIn("Alice", packet)
            self.assertNotIn("alice@example.com", packet)
            self.assertEqual(manifest["kind"], "review_packet_manifest")
            self.assertEqual(manifest["project_id"], 1)
            self.assertEqual(manifest["pii_status"], "anonymized")
            self.assertFalse(manifest["live_vault_write"])
            self.assertEqual(manifest["files"], ["review-packet-project-1.md"])
            self.assertEqual(manifest["inputs"]["obsidian_manifest"]["status"], "ok")

    def test_export_review_packet_includes_remaining_work_payload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db = tmp / "consulting.sqlite"
            leads_csv = tmp / "leads.csv"
            packet_dir = tmp / "review-packet-preview"
            self.write_leads_csv(leads_csv)

            self.run_cli("init-db", "--db", str(db))
            self.run_cli("import-leads", "--db", str(db), "--csv", str(leads_csv))
            self.run_cli("score-leads", "--db", str(db))
            self.run_cli("generate-proposal", "--db", str(db), "--lead-id", "1", "--out", str(tmp / "proposal.md"))

            self.run_cli(
                "export-review-packet",
                "--db",
                str(db),
                "--project-id",
                "1",
                "--output-dir",
                str(packet_dir),
            )

            packet = (packet_dir / "review-packet-project-1.md").read_text(encoding="utf-8")
            manifest = json.loads((packet_dir / "_review_packet_manifest.json").read_text(encoding="utf-8"))
            self.assertIn("next_action: generate-delivery-report", packet)
            self.assertIn("next_action: generate-delivery-checklist", packet)
            self.assertIn("next_action: generate-followup", packet)
            self.assertEqual(
                manifest["what_remains"]["missing_artifacts"],
                ["delivery_report", "delivery_checklist", "followups"],
            )
            self.assertEqual(
                manifest["what_remains"]["next_actions"],
                ["generate-delivery-report", "generate-delivery-checklist", "generate-followup"],
            )
            self.assertEqual(manifest["what_remains"]["optional_gates"], ["approve-case-study"])
            self.assertNotIn("Alice", packet + json.dumps(manifest, ensure_ascii=False))
            self.assertNotIn("alice@example.com", packet + json.dumps(manifest, ensure_ascii=False))

    def test_export_json_snapshot_writes_anonymized_local_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db = tmp / "consulting.sqlite"
            leads_csv = tmp / "leads.csv"
            snapshot = tmp / "status-snapshot.json"
            self.write_leads_csv(leads_csv)

            self.run_cli("init-db", "--db", str(db))
            self.run_cli("import-leads", "--db", str(db), "--csv", str(leads_csv))
            self.run_cli("score-leads", "--db", str(db))
            self.run_cli("generate-proposal", "--db", str(db), "--lead-id", "1", "--out", str(tmp / "proposal.md"))
            self.run_cli("generate-delivery-report", "--db", str(db), "--project-id", "1", "--out", str(tmp / "report.md"))
            self.run_cli("generate-delivery-checklist", "--db", str(db), "--project-id", "1", "--out", str(tmp / "checklist.md"))
            self.run_cli("mark-checklist-done", "--db", str(db), "--checklist-id", "1", "--note", "Reviewed")
            self.run_cli("generate-followup", "--db", str(db), "--project-id", "1", "--out", str(tmp / "followup.md"))
            self.run_cli("mark-followup-done", "--db", str(db), "--followup-id", "1", "--note", "Confirmed")

            self.run_cli("export-json-snapshot", "--db", str(db), "--out", str(snapshot))

            payload = json.loads(snapshot.read_text(encoding="utf-8"))
            self.assertEqual(payload["kind"], "consulting_crm_snapshot")
            self.assertEqual(payload["pii_status"], "anonymized")
            self.assertFalse(payload["live_vault_write"])
            self.assertEqual(payload["dashboard"]["leads"], 1)
            self.assertEqual(payload["dashboard"]["projects"], 1)
            self.assertEqual(payload["leads"][0]["lead_code"], "L-0001")
            self.assertEqual(payload["leads"][0]["client_alias"], "Client 1")
            self.assertEqual(payload["projects"][0]["project_id"], 1)
            self.assertEqual(payload["project_validations"][0]["ready_for_delivery"], True)
            self.assertEqual(payload["project_validations"][0]["delivery_checklist"]["done"], 1)
            self.assertEqual(payload["project_validations"][0]["followups"]["done"], 1)
            encoded = json.dumps(payload, ensure_ascii=False)
            self.assertNotIn("Alice", encoded)
            self.assertNotIn("alice@example.com", encoded)

    def test_export_json_snapshot_includes_queue_details(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db = tmp / "consulting.sqlite"
            leads_csv = tmp / "leads.csv"
            snapshot = tmp / "status-snapshot.json"
            self.write_leads_csv(leads_csv)

            self.run_cli("init-db", "--db", str(db))
            self.run_cli("import-leads", "--db", str(db), "--csv", str(leads_csv))
            self.run_cli("score-leads", "--db", str(db))
            self.run_cli("generate-proposal", "--db", str(db), "--lead-id", "1", "--out", str(tmp / "proposal.md"))
            self.run_cli("generate-delivery-checklist", "--db", str(db), "--project-id", "1", "--out", str(tmp / "checklist.md"))
            self.run_cli("mark-checklist-done", "--db", str(db), "--checklist-id", "1", "--note", "Reviewed")
            self.run_cli("generate-followup", "--db", str(db), "--project-id", "1", "--out", str(tmp / "followup.md"))
            self.run_cli("mark-followup-done", "--db", str(db), "--followup-id", "1", "--note", "Confirmed")

            self.run_cli("export-json-snapshot", "--db", str(db), "--out", str(snapshot))

            payload = json.loads(snapshot.read_text(encoding="utf-8"))
            self.assertIn("delivery_checklists", payload)
            self.assertIn("followup_queues", payload)
            self.assertEqual(payload["delivery_checklists"][0]["project_id"], 1)
            self.assertEqual(payload["delivery_checklists"][0]["items"][0]["status"], "done")
            self.assertEqual(payload["delivery_checklists"][0]["items"][0]["completion_note"], "Reviewed")
            self.assertEqual(payload["delivery_checklists"][0]["items"][1]["status"], "pending")
            self.assertEqual(payload["followup_queues"][0]["project_id"], 1)
            self.assertEqual(payload["followup_queues"][0]["followups"][0]["status"], "done")
            self.assertEqual(payload["followup_queues"][0]["followups"][0]["completion_note"], "Confirmed")
            self.assertEqual(payload["followup_queues"][0]["followups"][1]["status"], "planned")
            encoded = json.dumps(payload, ensure_ascii=False)
            self.assertNotIn("Alice", encoded)
            self.assertNotIn("alice@example.com", encoded)

    def test_export_json_snapshot_includes_case_study_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db = tmp / "consulting.sqlite"
            leads_csv = tmp / "leads.csv"
            snapshot = tmp / "status-snapshot.json"
            case_study = tmp / "case-study.md"
            self.write_leads_csv(leads_csv)

            self.run_cli("init-db", "--db", str(db))
            self.run_cli("import-leads", "--db", str(db), "--csv", str(leads_csv))
            self.run_cli("score-leads", "--db", str(db))
            self.run_cli("generate-proposal", "--db", str(db), "--lead-id", "1", "--out", str(tmp / "proposal.md"))
            self.run_cli("approve-case-study", "--db", str(db), "--project-id", "1", "--approved-by", "test")
            self.run_cli("export-case-study", "--db", str(db), "--project-id", "1", "--out", str(case_study))

            self.run_cli("export-json-snapshot", "--db", str(db), "--out", str(snapshot))

            payload = json.loads(snapshot.read_text(encoding="utf-8"))
            self.assertIn("case_studies", payload)
            self.assertEqual(len(payload["case_studies"]), 1)
            item = payload["case_studies"][0]
            self.assertEqual(item["project_id"], 1)
            self.assertEqual(item["client_alias"], "Client 1")
            self.assertEqual(item["status"], "draft")
            self.assertTrue(item["exported_at"])
            self.assertGreater(item["draft_char_count"], 0)
            self.assertNotIn("draft_markdown", item)
            encoded = json.dumps(payload, ensure_ascii=False)
            self.assertNotIn("Alice", encoded)
            self.assertNotIn("alice@example.com", encoded)


if __name__ == "__main__":
    unittest.main()
