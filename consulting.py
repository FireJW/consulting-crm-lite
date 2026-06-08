#!/usr/bin/env python3
"""Tiny local-first consulting CRM pilot.

This script intentionally stays small: CSV import, SQLite storage, simple lead
scoring, bilingual Markdown outputs, and an approval gate for case studies.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_DB = Path(".local") / "consulting-crm.sqlite"
CLASSIFICATIONS = {
    "not fit",
    "free content fit",
    "template/tool fit",
    "1v1 consultation fit",
    "course fit",
    "team consulting fit",
}


SCHEMA = """
create table if not exists leads (
  id integer primary key autoincrement,
  external_source text not null default '',
  external_id text not null default '',
  lead_code text not null unique,
  client_alias text not null,
  contact_hash text not null default '',
  role text not null default '',
  current_workflow text not null default '',
  pain_points_json text not null default '[]',
  tools_json text not null default '[]',
  desired_outcome text not null default '',
  budget_range text not null default '',
  time_urgency text not null default '',
  anonymized_profile_json text not null default '{}',
  created_at text not null
);

create table if not exists lead_scores (
  id integer primary key autoincrement,
  lead_id integer not null references leads(id),
  pain_intensity integer not null,
  budget integer not null,
  urgency integer not null,
  expertise_fit integer not null,
  repeatability integer not null,
  case_study_potential integer not null,
  total_score integer not null,
  classification text not null,
  recommended_offer text not null,
  rationale_json text not null default '[]',
  scored_at text not null
);

create table if not exists offers (
  id integer primary key autoincrement,
  code text not null unique,
  name_en text not null,
  name_zh text not null,
  target_classification text not null,
  price_band text not null,
  deliverables_json text not null
);

create table if not exists proposals (
  id integer primary key autoincrement,
  lead_id integer not null references leads(id),
  offer_code text not null,
  status text not null default 'draft',
  generated_markdown text not null,
  created_at text not null
);

create table if not exists delivery_projects (
  id integer primary key autoincrement,
  lead_id integer not null references leads(id),
  proposal_id integer,
  offer_code text not null,
  status text not null default 'draft',
  client_approved_for_case_study integer not null default 0,
  approval_snapshot_json text not null default '{}',
  created_at text not null
);

create table if not exists discovery_calls (
  id integer primary key autoincrement,
  lead_id integer not null references leads(id),
  project_id integer,
  summary text not null,
  current_state text not null default '',
  blockers text not null default '',
  desired_outcome text not null default '',
  next_step text not null default '',
  notes_markdown text not null,
  created_at text not null
);

create table if not exists delivery_checklists (
  id integer primary key autoincrement,
  project_id integer not null references delivery_projects(id),
  item_key text not null,
  item_label text not null,
  status text not null default 'pending',
  notes text not null default '',
  completion_note text not null default '',
  completed_at text not null default '',
  created_at text not null
);

create table if not exists reports (
  id integer primary key autoincrement,
  project_id integer not null references delivery_projects(id),
  report_type text not null,
  markdown text not null,
  created_at text not null
);

create table if not exists followups (
  id integer primary key autoincrement,
  project_id integer not null references delivery_projects(id),
  due_label text not null,
  channel text not null,
  purpose text not null,
  message_draft text not null,
  status text not null default 'planned',
  completion_note text not null default '',
  completed_at text not null default '',
  created_at text not null
);

create table if not exists case_studies (
  id integer primary key autoincrement,
  project_id integer not null references delivery_projects(id),
  status text not null,
  draft_markdown text not null,
  exported_at text not null
);
"""


OFFERS = [
    {
        "code": "workflow_audit_90m",
        "name_en": "90-minute workflow audit",
        "name_zh": "90 分钟工作流诊断",
        "target_classification": "1v1 consultation fit",
        "price_band": "starter",
        "deliverables": [
            "agenda",
            "pre-work checklist",
            "workflow diagnosis",
            "tool recommendations",
            "follow-up notes",
        ],
    },
    {
        "code": "workflow_sprint_3_session",
        "name_en": "3-session workflow sprint",
        "name_zh": "3 次工作流冲刺",
        "target_classification": "1v1 consultation fit",
        "price_band": "standard",
        "deliverables": [
            "workflow map",
            "implementation steps",
            "tool stack",
            "delivery checklist",
            "follow-up report",
        ],
    },
    {
        "code": "team_ai_workshop",
        "name_en": "team AI workflow workshop",
        "name_zh": "团队 AI 工作流工作坊",
        "target_classification": "team consulting fit",
        "price_band": "team",
        "deliverables": [
            "team agenda",
            "diagnosis framework",
            "workflow map",
            "implementation roadmap",
            "team checklist",
        ],
    },
    {
        "code": "course_recommendation",
        "name_en": "course recommendation",
        "name_zh": "课程推荐",
        "target_classification": "course fit",
        "price_band": "low",
        "deliverables": ["learning path", "recommended lessons", "practice checklist"],
    },
    {
        "code": "tool_template_pack",
        "name_en": "tool/template pack",
        "name_zh": "工具/模板包",
        "target_classification": "template/tool fit",
        "price_band": "low",
        "deliverables": ["template pack", "usage guide", "light follow-up checklist"],
    },
]


STANDARD_DELIVERY_CHECKLIST = [
    ("agenda", "Agenda"),
    ("pre_work_checklist", "Pre-work checklist"),
    ("diagnosis_framework", "Diagnosis framework"),
    ("workflow_map", "Workflow map"),
    ("recommended_tools", "Recommended tools"),
    ("implementation_steps", "Implementation steps"),
    ("followup_report", "Follow-up report"),
]


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_discovery_call_columns(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("pragma table_info(discovery_calls)").fetchall()}
    migrations = {
        "current_state": "text not null default ''",
        "blockers": "text not null default ''",
        "desired_outcome": "text not null default ''",
        "next_step": "text not null default ''",
    }
    for column, definition in migrations.items():
        if column not in columns:
            conn.execute(f"alter table discovery_calls add column {column} {definition}")
    conn.commit()


def ensure_status_metadata_columns(conn: sqlite3.Connection) -> None:
    migrations = {
        "completion_note": "text not null default ''",
        "completed_at": "text not null default ''",
    }
    for table in ("delivery_checklists", "followups"):
        columns = {row["name"] for row in conn.execute(f"pragma table_info({table})").fetchall()}
        for column, definition in migrations.items():
            if column not in columns:
                conn.execute(f"alter table {table} add column {column} {definition}")
    conn.commit()


def init_db(args: argparse.Namespace) -> int:
    conn = connect(Path(args.db))
    conn.executescript(SCHEMA)
    ensure_discovery_call_columns(conn)
    ensure_status_metadata_columns(conn)
    for offer in OFFERS:
        conn.execute(
            """
            insert into offers(code, name_en, name_zh, target_classification, price_band, deliverables_json)
            values (?, ?, ?, ?, ?, ?)
            on conflict(code) do update set
              name_en=excluded.name_en,
              name_zh=excluded.name_zh,
              target_classification=excluded.target_classification,
              price_band=excluded.price_band,
              deliverables_json=excluded.deliverables_json
            """,
            (
                offer["code"],
                offer["name_en"],
                offer["name_zh"],
                offer["target_classification"],
                offer["price_band"],
                json.dumps(offer["deliverables"], ensure_ascii=False),
            ),
        )
    conn.commit()
    print(f"Initialized DB / 已初始化数据库: {args.db}")
    return 0


def clean(value: Any) -> str:
    return str(value or "").strip()


def split_list(value: str) -> list[str]:
    return [item.strip() for item in clean(value).replace(";", ",").split(",") if item.strip()]


def contact_hash(row: dict[str, str]) -> str:
    raw = "|".join(clean(row.get(key)).lower() for key in ("name", "email", "company"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16] if raw.strip("|") else ""


def next_lead_code(conn: sqlite3.Connection) -> str:
    count = conn.execute("select count(*) from leads").fetchone()[0]
    return f"L-{count + 1:04d}"


def import_leads(args: argparse.Namespace) -> int:
    db_path = Path(args.db)
    conn = connect(db_path)
    conn.executescript(SCHEMA)
    imported = 0
    with Path(args.csv).open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            h = contact_hash(row)
            if h and conn.execute("select 1 from leads where contact_hash = ?", (h,)).fetchone():
                continue
            lead_code = next_lead_code(conn)
            client_alias = f"Client {int(lead_code.split('-')[1])}"
            pain_points = split_list(row.get("pain_points", ""))
            tools = split_list(row.get("ai_tools", ""))
            anonymized = {
                "client_alias": client_alias,
                "role": clean(row.get("role")),
                "workflow_summary": clean(row.get("current_workflow")),
                "pain_point_count": len(pain_points),
                "tool_count": len(tools),
                "desired_outcome": clean(row.get("desired_outcome")),
                "budget_range": clean(row.get("budget_range")) or "unknown",
                "time_urgency": clean(row.get("time_urgency")) or "unknown",
            }
            conn.execute(
                """
                insert into leads(
                  external_source, external_id, lead_code, client_alias, contact_hash,
                  role, current_workflow, pain_points_json, tools_json, desired_outcome,
                  budget_range, time_urgency, anonymized_profile_json, created_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    clean(row.get("source")) or "csv",
                    clean(row.get("external_id")),
                    lead_code,
                    client_alias,
                    h,
                    clean(row.get("role")),
                    clean(row.get("current_workflow")),
                    json.dumps(pain_points, ensure_ascii=False),
                    json.dumps(tools, ensure_ascii=False),
                    clean(row.get("desired_outcome")),
                    clean(row.get("budget_range")),
                    clean(row.get("time_urgency")),
                    json.dumps(anonymized, ensure_ascii=False),
                    now(),
                ),
            )
            imported += 1
    conn.commit()
    print(f"Imported leads / 已导入线索: {imported}")
    return 0


def score_budget(value: str) -> int:
    text = clean(value).lower()
    digits = [int(part) for part in "".join(ch if ch.isdigit() else " " for ch in text).split()]
    high = max(digits) if digits else 0
    if any(word in text for word in ("team", "enterprise", "high")) or high >= 5000:
        return 5
    if high >= 3000:
        return 4
    if high >= 1000:
        return 3
    if high > 0:
        return 2
    return 1


def score_urgency(value: str) -> int:
    text = clean(value).lower()
    if any(word in text for word in ("today", "this_week", "this week", "urgent", "asap", "now")):
        return 5
    if any(word in text for word in ("month", "soon", "2 weeks", "two weeks")):
        return 3
    return 1


def score_pain(pain_points: list[str]) -> int:
    text = " ".join(pain_points).lower()
    score = 1 + min(len(pain_points), 2)
    if any(word in text for word in ("wasting", "blocked", "bottleneck", "manual", "chaos", "repeat")):
        score += 2
    return min(score, 5)


def expertise_fit(lead: sqlite3.Row) -> int:
    text = " ".join(
        [
            lead["role"],
            lead["current_workflow"],
            lead["desired_outcome"],
            lead["pain_points_json"],
            lead["tools_json"],
        ]
    ).lower()
    score = 2
    for word in ("ai", "workflow", "product", "content", "automation", "template"):
        if word in text:
            score += 1
    return min(score, 5)


def repeatability(lead: sqlite3.Row) -> int:
    text = " ".join([lead["current_workflow"], lead["pain_points_json"], lead["desired_outcome"]]).lower()
    score = 2
    for word in ("weekly", "repeat", "reusable", "template", "system", "process"):
        if word in text:
            score += 1
    return min(score, 5)


def classify(total: int, budget: int, urgency: int, fit: int, repeat: int, role: str) -> str:
    role_text = role.lower()
    if total < 12 or fit <= 2:
        return "free content fit"
    if budget <= 2 and repeat >= 4:
        return "template/tool fit"
    if any(word in role_text for word in ("team", "manager", "lead", "head")) and budget >= 4:
        return "team consulting fit"
    if budget <= 2 and urgency <= 2:
        return "course fit"
    if total >= 20:
        return "1v1 consultation fit"
    return "template/tool fit"


def offer_for(classification: str, budget: int, urgency: int) -> str:
    if classification == "team consulting fit":
        return "team_ai_workshop"
    if classification == "course fit":
        return "course_recommendation"
    if classification == "template/tool fit":
        return "tool_template_pack"
    if classification == "1v1 consultation fit" and budget >= 4 and urgency >= 3:
        return "workflow_sprint_3_session"
    if classification == "1v1 consultation fit":
        return "workflow_audit_90m"
    return "course_recommendation"


def score_leads(args: argparse.Namespace) -> int:
    conn = connect(Path(args.db))
    leads = conn.execute("select * from leads order by id").fetchall()
    scored = 0
    for lead in leads:
        pain_points = json.loads(lead["pain_points_json"] or "[]")
        pain = score_pain(pain_points)
        budget = score_budget(lead["budget_range"])
        urgency = score_urgency(lead["time_urgency"])
        fit = expertise_fit(lead)
        repeat = repeatability(lead)
        case_study = 4 if repeat >= 4 and fit >= 4 else 2
        total = pain + budget + urgency + fit + repeat + case_study
        classification = classify(total, budget, urgency, fit, repeat, lead["role"])
        recommended_offer = offer_for(classification, budget, urgency)
        rationale = [
            f"pain={pain}",
            f"budget={budget}",
            f"urgency={urgency}",
            f"fit={fit}",
            f"repeatability={repeat}",
            f"case_study_potential={case_study}",
        ]
        conn.execute("delete from lead_scores where lead_id = ?", (lead["id"],))
        conn.execute(
            """
            insert into lead_scores(
              lead_id, pain_intensity, budget, urgency, expertise_fit, repeatability,
              case_study_potential, total_score, classification, recommended_offer,
              rationale_json, scored_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                lead["id"],
                pain,
                budget,
                urgency,
                fit,
                repeat,
                case_study,
                total,
                classification,
                recommended_offer,
                json.dumps(rationale, ensure_ascii=False),
                now(),
            ),
        )
        scored += 1
    conn.commit()
    print(f"Scored leads / 已评分线索: {scored}")
    return 0


def latest_score(conn: sqlite3.Connection, lead_id: int) -> sqlite3.Row:
    row = conn.execute(
        "select * from lead_scores where lead_id = ? order by scored_at desc, id desc limit 1",
        (lead_id,),
    ).fetchone()
    if not row:
        raise SystemExit("Lead is not scored yet / 线索尚未评分")
    return row


def get_offer(conn: sqlite3.Connection, code: str) -> sqlite3.Row:
    row = conn.execute("select * from offers where code = ?", (code,)).fetchone()
    if not row:
        raise SystemExit(f"Unknown offer / 未知服务包: {code}")
    return row


def render_offer(offer: sqlite3.Row) -> str:
    return f"{offer['name_en']} / {offer['name_zh']} ({offer['code']})"


def write_text(path: str, text: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def yaml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    text = clean(value)
    if text and all(ch.isalnum() or ch in "_-./" for ch in text):
        return text
    return json.dumps(text, ensure_ascii=False)


def frontmatter(fields: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in fields.items():
        lines.append(f"{key}: {yaml_value(value)}")
    lines.append("---")
    return "\n".join(lines)


def print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def assert_preview_output_dir(output_dir: Path) -> None:
    parts = [part.lower() for part in output_dir.parts]
    allowed = any(
        part in {".local", ".tmp", "tmp"} or part.startswith("tmp") or "preview" in part
        for part in parts
    )
    if not allowed:
        raise SystemExit(
            "export-obsidian is preview-only; --output-dir must include .local, tmp, .tmp, or preview / "
            "export-obsidian 仅允许预览目录"
        )


def write_obsidian_note(output_dir: Path, filename: str, text: str) -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / filename
    path.write_text(text, encoding="utf-8")
    return str(path)


def write_obsidian_manifest(output_dir: Path, manifest: dict[str, Any]) -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "_manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def write_review_packet_manifest(output_dir: Path, manifest: dict[str, Any]) -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "_review_packet_manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def generate_proposal(args: argparse.Namespace) -> int:
    conn = connect(Path(args.db))
    lead = conn.execute("select * from leads where id = ?", (args.lead_id,)).fetchone()
    if not lead:
        raise SystemExit("Lead not found / 未找到线索")
    score = latest_score(conn, lead["id"])
    offer = get_offer(conn, score["recommended_offer"])
    deliverables = json.loads(offer["deliverables_json"] or "[]")
    profile = json.loads(lead["anonymized_profile_json"] or "{}")
    markdown = "\n".join(
        [
            "# Consulting Proposal / 咨询提案",
            "",
            f"- Lead / 线索: {lead['lead_code']} ({lead['client_alias']})",
            f"- Role / 角色: {profile.get('role') or 'unknown'}",
            f"- Qualification / 资格判断: {score['classification']}",
            f"- Score / 评分: {score['total_score']}",
            f"- Recommended offer / 推荐服务包: {render_offer(offer)}",
            "",
            "## Scope / 范围",
            "- Diagnose the current AI/product workflow without inventing missing facts.",
            "- 诊断当前 AI / 产品工作流，不补写缺失事实。",
            "",
            "## Deliverables / 交付物",
            *[f"- {item}" for item in deliverables],
            "",
            "## Assumptions / 前提",
            "- Client details remain anonymized by default.",
            "- 默认匿名化客户信息。",
            "",
        ]
    )
    conn.execute(
        "insert into proposals(lead_id, offer_code, generated_markdown, created_at) values (?, ?, ?, ?)",
        (lead["id"], offer["code"], markdown, now()),
    )
    proposal_id = conn.execute("select last_insert_rowid()").fetchone()[0]
    conn.execute(
        """
        insert into delivery_projects(lead_id, proposal_id, offer_code, created_at)
        values (?, ?, ?, ?)
        """,
        (lead["id"], proposal_id, offer["code"], now()),
    )
    conn.commit()
    write_text(args.out, markdown)
    print(f"Wrote proposal / 已写入提案: {args.out}")
    return 0


def list_leads(args: argparse.Namespace) -> int:
    conn = connect(Path(args.db))
    conn.executescript(SCHEMA)
    rows = conn.execute(
        """
        select
          leads.lead_code,
          leads.client_alias,
          coalesce(scores.total_score, '') as total_score,
          coalesce(scores.classification, 'unscored') as classification,
          coalesce(scores.recommended_offer, '') as recommended_offer
        from leads
        left join lead_scores scores on scores.id = (
          select id from lead_scores
          where lead_id = leads.id
          order by scored_at desc, id desc
          limit 1
        )
        order by leads.id
        """
    ).fetchall()
    if args.format == "json":
        print_json(
            {
                "kind": "lead_list",
                "leads": [
                    {
                        "lead_code": row["lead_code"],
                        "client_alias": row["client_alias"],
                        "total_score": row["total_score"],
                        "classification": row["classification"],
                        "recommended_offer": row["recommended_offer"],
                    }
                    for row in rows
                ],
            }
        )
        return 0
    print("Leads / 线索")
    for row in rows:
        print(
            f"- {row['lead_code']} ({row['client_alias']}) "
            f"score={row['total_score']} classification={row['classification']} "
            f"offer={row['recommended_offer']}"
        )
    return 0


def generate_delivery_report(args: argparse.Namespace) -> int:
    conn = connect(Path(args.db))
    project = conn.execute("select * from delivery_projects where id = ?", (args.project_id,)).fetchone()
    if not project:
        raise SystemExit("Project not found / 未找到项目")
    lead = conn.execute("select * from leads where id = ?", (project["lead_id"],)).fetchone()
    offer = get_offer(conn, project["offer_code"])
    markdown = "\n".join(
        [
            "# Delivery Report / 交付报告",
            "",
            f"- Project / 项目: {project['id']}",
            f"- Client / 客户: {lead['client_alias']}",
            f"- Offer / 服务包: {render_offer(offer)}",
            "",
            "## Diagnosis / 诊断",
            "- Current workflow and pain points are summarized from imported lead data only.",
            "- 当前工作流和痛点只基于已导入线索数据总结。",
            "",
            "## Delivery checklist / 交付清单",
            "- Agenda / 议程",
            "- Pre-work checklist / 课前准备清单",
            "- Workflow map / 工作流地图",
            "- Recommended tools / 推荐工具",
            "- Implementation steps / 落地步骤",
            "",
            "## Follow-up plan / 跟进计划",
            "- Send summary within 48 hours.",
            "- 48 小时内发送总结。",
            "- Review implementation friction after 7 days.",
            "- 7 天后复盘落地阻力。",
            "",
        ]
    )
    conn.execute(
        "insert into reports(project_id, report_type, markdown, created_at) values (?, ?, ?, ?)",
        (project["id"], "delivery_report", markdown, now()),
    )
    conn.commit()
    write_text(args.out, markdown)
    print(f"Wrote delivery report / 已写入交付报告: {args.out}")
    return 0


def record_discovery_call(args: argparse.Namespace) -> int:
    conn = connect(Path(args.db))
    conn.executescript(SCHEMA)
    ensure_discovery_call_columns(conn)
    lead = conn.execute("select * from leads where id = ?", (args.lead_id,)).fetchone()
    if not lead:
        raise SystemExit("Lead not found")
    summary = clean(args.summary)
    if not summary:
        raise SystemExit("Discovery summary is required")
    current_state = clean(args.current_state or "")
    blockers = clean(args.blockers or "")
    desired_outcome = clean(args.desired_outcome or "")
    next_step = clean(args.next_step or "")
    project_id = args.project_id
    if project_id is not None:
        project = conn.execute("select * from delivery_projects where id = ?", (project_id,)).fetchone()
        if not project:
            raise SystemExit("Project not found")
    markdown = "\n".join(
        [
            "# Discovery Call Notes / 访谈记录",
            "",
            f"- Lead / 线索: {lead['lead_code']} ({lead['client_alias']})",
            f"- Project / 项目: {project_id if project_id is not None else 'not linked'}",
            "- PII status / 隐私状态: anonymized",
            "",
            "## Summary / 摘要",
            summary,
            "",
            "## Structured Fields / 结构化字段",
            f"- Current state / 现状: {current_state or 'not provided'}",
            f"- Blockers / 阻塞点: {blockers or 'not provided'}",
            f"- Desired outcome / 目标结果: {desired_outcome or 'not provided'}",
            f"- Next step / 下一步: {next_step or 'not provided'}",
            "",
            "## Guardrails / 约束",
            "- Do not add client facts that were not provided.",
            "- Keep real names, email addresses, and company details out of this note by default.",
            "",
        ]
    )
    conn.execute(
        """
        insert into discovery_calls(
          lead_id, project_id, summary, current_state, blockers,
          desired_outcome, next_step, notes_markdown, created_at
        )
        values (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            lead["id"],
            project_id,
            summary,
            current_state,
            blockers,
            desired_outcome,
            next_step,
            markdown,
            now(),
        ),
    )
    conn.commit()
    write_text(args.out, markdown)
    print(f"Wrote discovery call notes / 已写入访谈记录: {args.out}")
    return 0


def generate_delivery_checklist(args: argparse.Namespace) -> int:
    conn = connect(Path(args.db))
    conn.executescript(SCHEMA)
    project = conn.execute("select * from delivery_projects where id = ?", (args.project_id,)).fetchone()
    if not project:
        raise SystemExit("Project not found")
    lead = conn.execute("select * from leads where id = ?", (project["lead_id"],)).fetchone()
    offer = get_offer(conn, project["offer_code"])
    conn.execute("delete from delivery_checklists where project_id = ?", (project["id"],))
    created_at = now()
    for item_key, item_label in STANDARD_DELIVERY_CHECKLIST:
        conn.execute(
            """
            insert into delivery_checklists(project_id, item_key, item_label, status, created_at)
            values (?, ?, ?, ?, ?)
            """,
            (project["id"], item_key, item_label, "pending", created_at),
        )
    conn.commit()
    lines = [
        "# Delivery Checklist / 交付清单",
        "",
        f"- Project / 项目: {project['id']}",
        f"- Client / 客户: {lead['client_alias']}",
        f"- Offer / 服务包: {render_offer(offer)}",
        "- PII status / 隐私状态: anonymized",
        "",
    ]
    for _, item_label in STANDARD_DELIVERY_CHECKLIST:
        lines.append(f"- [ ] {item_label}")
    lines.append("")
    markdown = "\n".join(lines)
    write_text(args.out, markdown)
    print(f"Wrote delivery checklist / 已写入交付清单: {args.out}")
    return 0


def list_delivery_checklist(args: argparse.Namespace) -> int:
    conn = connect(Path(args.db))
    conn.executescript(SCHEMA)
    ensure_status_metadata_columns(conn)
    project = conn.execute("select * from delivery_projects where id = ?", (args.project_id,)).fetchone()
    if not project:
        raise SystemExit("Project not found")
    lead = conn.execute("select * from leads where id = ?", (project["lead_id"],)).fetchone()
    rows = conn.execute(
        """
        select id, item_key, item_label, status, completion_note, completed_at
        from delivery_checklists
        where project_id = ?
        order by id
        """,
        (project["id"],),
    ).fetchall()
    if args.format == "json":
        print_json(
            {
                "kind": "delivery_checklist",
                "project_id": project["id"],
                "client_alias": lead["client_alias"],
                "items": [
                    {
                        "id": row["id"],
                        "item_key": row["item_key"],
                        "item_label": row["item_label"],
                        "status": row["status"],
                        "completion_note": row["completion_note"],
                        "completed_at": row["completed_at"],
                    }
                    for row in rows
                ],
            }
        )
        return 0
    print(f"Delivery checklist / 交付清单: project {project['id']} ({lead['client_alias']})")
    for row in rows:
        print(f"- #{row['id']} [{row['status']}] {row['item_label']}")
    return 0


def mark_checklist_done(args: argparse.Namespace) -> int:
    conn = connect(Path(args.db))
    conn.executescript(SCHEMA)
    ensure_status_metadata_columns(conn)
    row = conn.execute("select * from delivery_checklists where id = ?", (args.checklist_id,)).fetchone()
    if not row:
        raise SystemExit("Checklist item not found")
    conn.execute(
        "update delivery_checklists set status = ?, completion_note = ?, completed_at = ? where id = ?",
        ("done", clean(args.note or ""), now(), args.checklist_id),
    )
    conn.commit()
    print(f"Marked checklist item done / 已完成交付清单项: #{args.checklist_id}")
    return 0


def reopen_checklist_item(args: argparse.Namespace) -> int:
    conn = connect(Path(args.db))
    conn.executescript(SCHEMA)
    ensure_status_metadata_columns(conn)
    row = conn.execute("select * from delivery_checklists where id = ?", (args.checklist_id,)).fetchone()
    if not row:
        raise SystemExit("Checklist item not found")
    conn.execute(
        "update delivery_checklists set status = ?, completion_note = ?, completed_at = ? where id = ?",
        ("pending", "", "", args.checklist_id),
    )
    conn.commit()
    print(f"Reopened checklist item / 已重开交付清单项: #{args.checklist_id}")
    return 0


def build_followup_steps(lead: sqlite3.Row, offer: sqlite3.Row) -> list[dict[str, str]]:
    client = lead["client_alias"]
    offer_label = render_offer(offer)
    return [
        {
            "due_label": "48 hours",
            "channel": "email/manual",
            "purpose": "delivery_summary",
            "message_draft": (
                f"Hi {client}, here is the concise summary of the {offer_label}. "
                "Please mark anything inaccurate before we turn it into implementation notes."
            ),
            "purpose_zh": "交付总结",
            "message_zh": f"{client}，这是本次 {offer_label} 的简要总结。请先确认是否有不准确之处，再进入落地记录。",
        },
        {
            "due_label": "7 days",
            "channel": "email/manual",
            "purpose": "implementation_friction_check",
            "message_draft": (
                f"Hi {client}, which step created the most friction after the first week? "
                "Reply with one blocker and one workflow win if available."
            ),
            "purpose_zh": "落地阻力检查",
            "message_zh": f"{client}，第一周落地后，哪一步阻力最大？如果方便，请回复一个阻塞点和一个有效动作。",
        },
        {
            "due_label": "30 days",
            "channel": "email/manual",
            "purpose": "upgrade_or_case_study_review",
            "message_draft": (
                f"Hi {client}, should we review whether this workflow is ready for a next sprint, "
                "template pack, or approved anonymized case study?"
            ),
            "purpose_zh": "升级或案例复盘",
            "message_zh": f"{client}，是否需要复盘这套工作流是否适合进入下一轮冲刺、模板包，或经批准后的匿名案例？",
        },
    ]


def generate_followup(args: argparse.Namespace) -> int:
    conn = connect(Path(args.db))
    conn.executescript(SCHEMA)
    project = conn.execute("select * from delivery_projects where id = ?", (args.project_id,)).fetchone()
    if not project:
        raise SystemExit("Project not found / 未找到项目")
    lead = conn.execute("select * from leads where id = ?", (project["lead_id"],)).fetchone()
    offer = get_offer(conn, project["offer_code"])
    steps = build_followup_steps(lead, offer)
    conn.execute("delete from followups where project_id = ?", (project["id"],))
    for step in steps:
        conn.execute(
            """
            insert into followups(project_id, due_label, channel, purpose, message_draft, created_at)
            values (?, ?, ?, ?, ?, ?)
            """,
            (
                project["id"],
                step["due_label"],
                step["channel"],
                step["purpose"],
                step["message_draft"],
                now(),
            ),
        )
    conn.commit()
    lines = [
        "# Follow-up Plan / 跟进计划",
        "",
        f"- Project / 项目: {project['id']}",
        f"- Client / 客户: {lead['client_alias']}",
        f"- Offer / 服务包: {render_offer(offer)}",
        "",
    ]
    for step in steps:
        lines.extend(
            [
                f"## {step['due_label']} / {step['purpose_zh']}",
                f"- Channel / 渠道: {step['channel']}",
                f"- Purpose / 目的: {step['purpose']} / {step['purpose_zh']}",
                "",
                "English:",
                step["message_draft"],
                "",
                "中文:",
                step["message_zh"],
                "",
            ]
        )
    markdown = "\n".join(lines)
    write_text(args.out, markdown)
    print(f"Wrote follow-up plan / 已写入跟进计划: {args.out}")
    return 0


def list_followups(args: argparse.Namespace) -> int:
    conn = connect(Path(args.db))
    conn.executescript(SCHEMA)
    ensure_status_metadata_columns(conn)
    project = conn.execute("select * from delivery_projects where id = ?", (args.project_id,)).fetchone()
    if not project:
        raise SystemExit("Project not found")
    lead = conn.execute("select * from leads where id = ?", (project["lead_id"],)).fetchone()
    rows = conn.execute(
        """
        select id, due_label, channel, purpose, status, completion_note, completed_at
        from followups
        where project_id = ?
        order by id
        """,
        (project["id"],),
    ).fetchall()
    if args.format == "json":
        print_json(
            {
                "kind": "followup_queue",
                "project_id": project["id"],
                "client_alias": lead["client_alias"],
                "followups": [
                    {
                        "id": row["id"],
                        "due_label": row["due_label"],
                        "channel": row["channel"],
                        "purpose": row["purpose"],
                        "status": row["status"],
                        "completion_note": row["completion_note"],
                        "completed_at": row["completed_at"],
                    }
                    for row in rows
                ],
            }
        )
        return 0
    print(f"Follow-ups / 跟进队列: project {project['id']} ({lead['client_alias']})")
    for row in rows:
        print(f"- #{row['id']} [{row['status']}] {row['due_label']} :: {row['purpose']}")
    return 0


def mark_followup_done(args: argparse.Namespace) -> int:
    conn = connect(Path(args.db))
    conn.executescript(SCHEMA)
    ensure_status_metadata_columns(conn)
    row = conn.execute("select * from followups where id = ?", (args.followup_id,)).fetchone()
    if not row:
        raise SystemExit("Follow-up not found")
    conn.execute(
        "update followups set status = ?, completion_note = ?, completed_at = ? where id = ?",
        ("done", clean(args.note or ""), now(), args.followup_id),
    )
    conn.commit()
    print(f"Marked follow-up done / 已完成跟进: #{args.followup_id}")
    return 0


def reopen_followup(args: argparse.Namespace) -> int:
    conn = connect(Path(args.db))
    conn.executescript(SCHEMA)
    ensure_status_metadata_columns(conn)
    row = conn.execute("select * from followups where id = ?", (args.followup_id,)).fetchone()
    if not row:
        raise SystemExit("Follow-up not found")
    conn.execute(
        "update followups set status = ?, completion_note = ?, completed_at = ? where id = ?",
        ("planned", "", "", args.followup_id),
    )
    conn.commit()
    print(f"Reopened follow-up / 已重开跟进: #{args.followup_id}")
    return 0


def followup_status_counts(conn: sqlite3.Connection, project_id: int) -> dict[str, int]:
    rows = conn.execute(
        "select status, count(*) as count from followups where project_id = ? group by status",
        (project_id,),
    ).fetchall()
    return {row["status"]: row["count"] for row in rows}


def dashboard_payload(conn: sqlite3.Connection) -> dict[str, Any]:
    followups = {
        row["status"]: row["count"]
        for row in conn.execute("select status, count(*) as count from followups group by status").fetchall()
    }
    checklist = {
        row["status"]: row["count"]
        for row in conn.execute("select status, count(*) as count from delivery_checklists group by status").fetchall()
    }
    return {
        "leads": conn.execute("select count(*) from leads").fetchone()[0],
        "projects": conn.execute("select count(*) from delivery_projects").fetchone()[0],
        "case_study_approved": conn.execute(
            "select count(*) from delivery_projects where client_approved_for_case_study = 1"
        ).fetchone()[0],
        "followups": {
            "done": followups.get("done", 0),
            "planned": followups.get("planned", 0),
        },
        "delivery_checklist": {
            "done": checklist.get("done", 0),
            "pending": checklist.get("pending", 0),
        },
    }


def lead_rows_payload(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        select
          leads.lead_code,
          leads.client_alias,
          coalesce(scores.total_score, '') as total_score,
          coalesce(scores.classification, 'unscored') as classification,
          coalesce(scores.recommended_offer, '') as recommended_offer
        from leads
        left join lead_scores scores on scores.id = (
          select id from lead_scores
          where lead_id = leads.id
          order by scored_at desc, id desc
          limit 1
        )
        order by leads.id
        """
    ).fetchall()
    return [
        {
            "lead_code": row["lead_code"],
            "client_alias": row["client_alias"],
            "total_score": row["total_score"],
            "classification": row["classification"],
            "recommended_offer": row["recommended_offer"],
        }
        for row in rows
    ]


def project_rows_payload(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        select
          projects.id,
          projects.offer_code,
          projects.status,
          projects.client_approved_for_case_study,
          leads.client_alias
        from delivery_projects projects
        join leads on leads.id = projects.lead_id
        order by projects.id
        """
    ).fetchall()
    return [
        {
            "project_id": row["id"],
            "client_alias": row["client_alias"],
            "offer_code": row["offer_code"],
            "status": row["status"],
            "case_study_approved": bool(row["client_approved_for_case_study"]),
        }
        for row in rows
    ]


def project_validation_payload(conn: sqlite3.Connection, project: sqlite3.Row) -> dict[str, Any]:
    proposal_count = 0
    if project["proposal_id"]:
        proposal_count = conn.execute(
            "select count(*) from proposals where id = ?",
            (project["proposal_id"],),
        ).fetchone()[0]
    report_count = conn.execute(
        "select count(*) from reports where project_id = ?",
        (project["id"],),
    ).fetchone()[0]
    checklist = {
        row["status"]: row["count"]
        for row in conn.execute(
            "select status, count(*) as count from delivery_checklists where project_id = ? group by status",
            (project["id"],),
        ).fetchall()
    }
    followups = followup_status_counts(conn, project["id"])
    checklist_count = sum(checklist.values())
    followup_count = sum(followups.values())
    ready = proposal_count > 0 and report_count > 0 and checklist_count > 0 and followup_count > 0
    return {
        "kind": "project_validation",
        "project_id": project["id"],
        "lead_code": project["lead_code"],
        "client_alias": project["client_alias"],
        "proposal": {"status": "ok" if proposal_count else "missing"},
        "delivery_report": {"status": "ok" if report_count else "missing"},
        "delivery_checklist": (
            {
                "status": "ok",
                "count": checklist_count,
                "done": checklist.get("done", 0),
                "pending": checklist.get("pending", 0),
            }
            if checklist_count
            else {"status": "missing", "count": 0, "done": 0, "pending": 0}
        ),
        "followups": (
            {
                "status": "ok",
                "count": followup_count,
                "done": followups.get("done", 0),
                "planned": followups.get("planned", 0),
            }
            if followup_count
            else {"status": "missing", "count": 0, "done": 0, "planned": 0}
        ),
        "case_study_approved": bool(project["client_approved_for_case_study"]),
        "ready_for_delivery": ready,
    }


def what_remains_payload(validation: dict[str, Any]) -> dict[str, Any]:
    missing_artifacts = []
    next_actions = []
    for artifact, action in (
        ("delivery_report", "generate-delivery-report"),
        ("delivery_checklist", "generate-delivery-checklist"),
        ("followups", "generate-followup"),
    ):
        if validation[artifact]["status"] != "ok":
            missing_artifacts.append(artifact)
            next_actions.append(action)
    optional_gates = []
    if not validation["case_study_approved"]:
        optional_gates.append("approve-case-study")
    return {
        "kind": "what_remains",
        "project_id": validation["project_id"],
        "lead_code": validation["lead_code"],
        "client_alias": validation["client_alias"],
        "ready_for_delivery": validation["ready_for_delivery"],
        "case_study_approved": validation["case_study_approved"],
        "missing_artifacts": missing_artifacts,
        "next_actions": next_actions,
        "optional_gates": optional_gates,
        "validation": validation,
    }


def case_study_approval_payload(conn: sqlite3.Connection, project_id: int) -> dict[str, Any]:
    project = conn.execute(
        """
        select
          projects.id,
          projects.client_approved_for_case_study,
          projects.approval_snapshot_json,
          leads.lead_code,
          leads.client_alias
        from delivery_projects projects
        join leads on leads.id = projects.lead_id
        where projects.id = ?
        """,
        (project_id,),
    ).fetchone()
    if not project:
        raise SystemExit("Project not found / 未找到项目")
    return {
        "kind": "case_study_approval",
        "project_id": project["id"],
        "lead_code": project["lead_code"],
        "client_alias": project["client_alias"],
        "case_study_approved": bool(project["client_approved_for_case_study"]),
        "approval_snapshot": json.loads(project["approval_snapshot_json"] or "{}"),
    }


def delivery_checklist_snapshot_payload(conn: sqlite3.Connection, project: sqlite3.Row) -> dict[str, Any]:
    rows = conn.execute(
        """
        select id, item_key, item_label, status, completion_note, completed_at
        from delivery_checklists
        where project_id = ?
        order by id
        """,
        (project["id"],),
    ).fetchall()
    return {
        "project_id": project["id"],
        "client_alias": project["client_alias"],
        "items": [
            {
                "id": row["id"],
                "item_key": row["item_key"],
                "item_label": row["item_label"],
                "status": row["status"],
                "completion_note": row["completion_note"],
                "completed_at": row["completed_at"],
            }
            for row in rows
        ],
    }


def followup_queue_snapshot_payload(conn: sqlite3.Connection, project: sqlite3.Row) -> dict[str, Any]:
    rows = conn.execute(
        """
        select id, due_label, channel, purpose, status, completion_note, completed_at
        from followups
        where project_id = ?
        order by id
        """,
        (project["id"],),
    ).fetchall()
    return {
        "project_id": project["id"],
        "client_alias": project["client_alias"],
        "followups": [
            {
                "id": row["id"],
                "due_label": row["due_label"],
                "channel": row["channel"],
                "purpose": row["purpose"],
                "status": row["status"],
                "completion_note": row["completion_note"],
                "completed_at": row["completed_at"],
            }
            for row in rows
        ],
    }


def case_studies_snapshot_payload(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        select
          case_studies.id,
          case_studies.project_id,
          case_studies.status,
          case_studies.draft_markdown,
          case_studies.exported_at,
          leads.lead_code,
          leads.client_alias
        from case_studies
        join delivery_projects projects on projects.id = case_studies.project_id
        join leads on leads.id = projects.lead_id
        order by case_studies.id
        """
    ).fetchall()
    return [
        {
            "id": row["id"],
            "project_id": row["project_id"],
            "lead_code": row["lead_code"],
            "client_alias": row["client_alias"],
            "status": row["status"],
            "exported_at": row["exported_at"],
            "draft_char_count": len(row["draft_markdown"] or ""),
        }
        for row in rows
    ]


def list_projects(args: argparse.Namespace) -> int:
    conn = connect(Path(args.db))
    conn.executescript(SCHEMA)
    rows = conn.execute(
        """
        select
          projects.id,
          projects.offer_code,
          projects.status,
          projects.client_approved_for_case_study,
          leads.client_alias
        from delivery_projects projects
        join leads on leads.id = projects.lead_id
        order by projects.id
        """
    ).fetchall()
    if args.format == "json":
        print_json(
            {
                "kind": "project_list",
                "projects": [
                    {
                        "project_id": row["id"],
                        "client_alias": row["client_alias"],
                        "offer_code": row["offer_code"],
                        "status": row["status"],
                        "case_study_approved": bool(row["client_approved_for_case_study"]),
                    }
                    for row in rows
                ],
            }
        )
        return 0
    print("Projects / 项目")
    for row in rows:
        approved = "true" if row["client_approved_for_case_study"] else "false"
        print(
            f"- project {row['id']} ({row['client_alias']}) "
            f"offer={row['offer_code']} status={row['status']} "
            f"case_study_approved={approved}"
        )
    return 0


def show_project(args: argparse.Namespace) -> int:
    conn = connect(Path(args.db))
    conn.executescript(SCHEMA)
    project = conn.execute(
        """
        select
          projects.*,
          leads.lead_code,
          leads.client_alias
        from delivery_projects projects
        join leads on leads.id = projects.lead_id
        where projects.id = ?
        """,
        (args.project_id,),
    ).fetchone()
    if not project:
        raise SystemExit("Project not found")
    approved = "true" if project["client_approved_for_case_study"] else "false"
    counts = followup_status_counts(conn, project["id"])
    done = counts.get("done", 0)
    planned = counts.get("planned", 0)
    if args.format == "json":
        print_json(
            {
                "kind": "project",
                "project_id": project["id"],
                "lead_code": project["lead_code"],
                "client_alias": project["client_alias"],
                "offer_code": project["offer_code"],
                "status": project["status"],
                "case_study_approved": bool(project["client_approved_for_case_study"]),
                "followups": {"done": done, "planned": planned},
            }
        )
        return 0
    print(f"Project {project['id']} / 项目 {project['id']}")
    print(f"- Lead / 线索: {project['lead_code']} ({project['client_alias']})")
    print(f"- Offer / 服务包: {project['offer_code']}")
    print(f"- Status / 状态: {project['status']}")
    print(f"- case_study_approved={approved}")
    print(f"- Follow-ups / 跟进: done={done} planned={planned}")
    return 0


def dashboard(args: argparse.Namespace) -> int:
    conn = connect(Path(args.db))
    conn.executescript(SCHEMA)
    lead_count = conn.execute("select count(*) from leads").fetchone()[0]
    project_count = conn.execute("select count(*) from delivery_projects").fetchone()[0]
    approved_count = conn.execute(
        "select count(*) from delivery_projects where client_approved_for_case_study = 1"
    ).fetchone()[0]
    followups = {
        row["status"]: row["count"]
        for row in conn.execute("select status, count(*) as count from followups group by status").fetchall()
    }
    checklist = {
        row["status"]: row["count"]
        for row in conn.execute("select status, count(*) as count from delivery_checklists group by status").fetchall()
    }
    payload = {
        "kind": "dashboard",
        "leads": lead_count,
        "projects": project_count,
        "case_study_approved": approved_count,
        "followups": {
            "done": followups.get("done", 0),
            "planned": followups.get("planned", 0),
        },
        "delivery_checklist": {
            "done": checklist.get("done", 0),
            "pending": checklist.get("pending", 0),
        },
    }
    if args.format == "json":
        print_json(payload)
        return 0
    print("Dashboard / 仪表盘")
    print(f"- leads={payload['leads']}")
    print(f"- projects={payload['projects']}")
    print(f"- case_study_approved={payload['case_study_approved']}")
    print(f"- followups: done={payload['followups']['done']} planned={payload['followups']['planned']}")
    print(
        f"- delivery_checklist: done={payload['delivery_checklist']['done']} "
        f"pending={payload['delivery_checklist']['pending']}"
    )
    return 0


def validate_project(args: argparse.Namespace) -> int:
    conn = connect(Path(args.db))
    conn.executescript(SCHEMA)
    project = conn.execute(
        """
        select
          projects.*,
          leads.lead_code,
          leads.client_alias
        from delivery_projects projects
        join leads on leads.id = projects.lead_id
        where projects.id = ?
        """,
        (args.project_id,),
    ).fetchone()
    if not project:
        raise SystemExit("Project not found")

    proposal_count = 0
    if project["proposal_id"]:
        proposal_count = conn.execute(
            "select count(*) from proposals where id = ?",
            (project["proposal_id"],),
        ).fetchone()[0]
    report_count = conn.execute(
        "select count(*) from reports where project_id = ?",
        (project["id"],),
    ).fetchone()[0]
    checklist = {
        row["status"]: row["count"]
        for row in conn.execute(
            "select status, count(*) as count from delivery_checklists where project_id = ? group by status",
            (project["id"],),
        ).fetchall()
    }
    followups = {
        row["status"]: row["count"]
        for row in conn.execute(
            "select status, count(*) as count from followups where project_id = ? group by status",
            (project["id"],),
        ).fetchall()
    }
    checklist_count = sum(checklist.values())
    followup_count = sum(followups.values())
    ready = proposal_count > 0 and report_count > 0 and checklist_count > 0 and followup_count > 0
    approved_bool = bool(project["client_approved_for_case_study"])
    approved = "true" if approved_bool else "false"

    payload = {
        "kind": "project_validation",
        "project_id": project["id"],
        "lead_code": project["lead_code"],
        "client_alias": project["client_alias"],
        "proposal": {"status": "ok" if proposal_count else "missing"},
        "delivery_report": {"status": "ok" if report_count else "missing"},
        "delivery_checklist": (
            {
                "status": "ok",
                "count": checklist_count,
                "done": checklist.get("done", 0),
                "pending": checklist.get("pending", 0),
            }
            if checklist_count
            else {"status": "missing", "count": 0, "done": 0, "pending": 0}
        ),
        "followups": (
            {
                "status": "ok",
                "count": followup_count,
                "done": followups.get("done", 0),
                "planned": followups.get("planned", 0),
            }
            if followup_count
            else {"status": "missing", "count": 0, "done": 0, "planned": 0}
        ),
        "case_study_approved": approved_bool,
        "ready_for_delivery": ready,
    }

    if args.format == "json":
        print_json(payload)
        return 0 if ready else 1

    print(f"Project validation / 项目检查: project {project['id']} ({project['client_alias']})")
    print(f"- proposal: {payload['proposal']['status']}")
    print(f"- delivery_report: {payload['delivery_report']['status']}")
    if checklist_count:
        print(
            f"- delivery_checklist: ok count={checklist_count} "
            f"done={checklist.get('done', 0)} pending={checklist.get('pending', 0)}"
        )
    else:
        print("- delivery_checklist: missing")
    if followup_count:
        print(
            f"- followups: ok count={followup_count} "
            f"done={followups.get('done', 0)} planned={followups.get('planned', 0)}"
        )
    else:
        print("- followups: missing")
    print(f"- case_study_approved={approved}")
    print(f"- ready_for_delivery={'true' if ready else 'false'}")
    return 0 if ready else 1


def what_remains(args: argparse.Namespace) -> int:
    conn = connect(Path(args.db))
    conn.executescript(SCHEMA)
    project = conn.execute(
        """
        select
          projects.*,
          leads.lead_code,
          leads.client_alias
        from delivery_projects projects
        join leads on leads.id = projects.lead_id
        where projects.id = ?
        """,
        (args.project_id,),
    ).fetchone()
    if not project:
        raise SystemExit("Project not found")

    payload = what_remains_payload(project_validation_payload(conn, project))
    actions = payload["next_actions"]

    if args.format == "json":
        print_json(payload)
        return 0 if payload["ready_for_delivery"] else 1
    print(f"What remains / 剩余任务: project {project['id']} ({project['client_alias']})")
    print(f"- ready_for_delivery={'true' if payload['ready_for_delivery'] else 'false'}")
    print(f"- case_study_approved={'true' if payload['case_study_approved'] else 'false'}")
    if actions:
        print("- Next actions / 下一步:")
        for action in actions:
            print(f"  - {action}")
    else:
        print("- No required delivery artifacts are missing.")
    if not payload["case_study_approved"]:
        print("- Optional gate: approve-case-study before exporting a case study.")
    return 0 if payload["ready_for_delivery"] else 1


def approve_case_study(args: argparse.Namespace) -> int:
    conn = connect(Path(args.db))
    project = conn.execute("select * from delivery_projects where id = ?", (args.project_id,)).fetchone()
    if not project:
        raise SystemExit("Project not found / 未找到项目")
    snapshot = {"approved_by": args.approved_by, "approved_at": now(), "approval_mode": "manual_local"}
    conn.execute(
        """
        update delivery_projects
        set client_approved_for_case_study = 1, approval_snapshot_json = ?
        where id = ?
        """,
        (json.dumps(snapshot, ensure_ascii=False), args.project_id),
    )
    conn.commit()
    if args.format == "json":
        print_json(case_study_approval_payload(conn, args.project_id))
        return 0
    print(f"Approved case study / 已批准案例导出: project {args.project_id}")
    return 0


def revoke_case_study_approval(args: argparse.Namespace) -> int:
    conn = connect(Path(args.db))
    project = conn.execute("select * from delivery_projects where id = ?", (args.project_id,)).fetchone()
    if not project:
        raise SystemExit("Project not found / 未找到项目")
    conn.execute(
        """
        update delivery_projects
        set client_approved_for_case_study = 0, approval_snapshot_json = '{}'
        where id = ?
        """,
        (args.project_id,),
    )
    conn.commit()
    if args.format == "json":
        print_json(case_study_approval_payload(conn, args.project_id))
        return 0
    print(f"Revoked case study approval / 已撤销案例批准: project {args.project_id}")
    return 0


def export_case_study(args: argparse.Namespace) -> int:
    conn = connect(Path(args.db))
    project = conn.execute("select * from delivery_projects where id = ?", (args.project_id,)).fetchone()
    if not project:
        raise SystemExit("Project not found / 未找到项目")
    if not project["client_approved_for_case_study"]:
        raise SystemExit("Blocked: client_approved_for_case_study is false / 已阻止：客户尚未批准案例")
    lead = conn.execute("select * from leads where id = ?", (project["lead_id"],)).fetchone()
    offer = get_offer(conn, project["offer_code"])
    profile = json.loads(lead["anonymized_profile_json"] or "{}")
    markdown = "\n".join(
        [
            "# Case Study Draft / 案例草稿",
            "",
            f"- Client / 客户: {lead['client_alias']}",
            f"- Role / 角色: {profile.get('role') or 'unknown'}",
            f"- Offer / 服务包: {render_offer(offer)}",
            "",
            "## Before / 之前",
            f"- Workflow / 工作流: {profile.get('workflow_summary') or 'unknown'}",
            "",
            "## Intervention / 介入",
            "- AI workflow diagnosis, offer-matched delivery, and follow-up plan.",
            "- AI 工作流诊断、匹配服务包交付、跟进计划。",
            "",
            "## Result / 结果",
            "- Outcome not claimed unless supported by delivery records.",
            "- 未有交付记录支持时，不宣称具体结果。",
            "",
        ]
    )
    cursor = conn.execute(
        "insert into case_studies(project_id, status, draft_markdown, exported_at) values (?, ?, ?, ?)",
        (project["id"], "draft", markdown, now()),
    )
    conn.commit()
    write_text(args.out, markdown)
    if args.format == "json":
        print_json(
            {
                "kind": "case_study_export",
                "case_study_id": cursor.lastrowid,
                "project_id": project["id"],
                "lead_code": lead["lead_code"],
                "client_alias": lead["client_alias"],
                "status": "draft",
                "output_path": str(args.out),
                "pii_status": "anonymized",
                "draft_char_count": len(markdown),
            }
        )
        return 0
    print(f"Wrote case study draft / 已写入案例草稿: {args.out}")
    return 0


def render_lead_obsidian_note(lead: sqlite3.Row, score: sqlite3.Row, offer: sqlite3.Row) -> str:
    profile = json.loads(lead["anonymized_profile_json"] or "{}")
    fields = {
        "kb_type": "consulting_delivery",
        "consulting_type": "lead",
        "lead_code": lead["lead_code"],
        "client_alias": lead["client_alias"],
        "offer_code": offer["code"],
        "classification": score["classification"],
        "case_study_approved": False,
        "source_db_id": lead["id"],
        "generated_at": now(),
        "pii_status": "anonymized",
        "managed_by": "codex",
        "review_state": "draft",
    }
    return "\n".join(
        [
            frontmatter(fields),
            "",
            f"# {lead['client_alias']} Lead / 线索",
            "",
            "## Lead qualification / 线索资格判断",
            f"- Score / 评分: {score['total_score']}",
            f"- Classification / 分类: {score['classification']}",
            f"- Recommended offer / 推荐服务包: {render_offer(offer)}",
            "",
            "## Anonymized profile / 匿名画像",
            f"- Role / 角色: {profile.get('role') or 'unknown'}",
            f"- Workflow / 工作流: {profile.get('workflow_summary') or 'unknown'}",
            f"- Pain point count / 痛点数量: {profile.get('pain_point_count', 0)}",
            f"- Tool count / 工具数量: {profile.get('tool_count', 0)}",
            f"- Desired outcome / 目标结果: {profile.get('desired_outcome') or 'unknown'}",
            f"- Budget range / 预算范围: {profile.get('budget_range') or 'unknown'}",
            f"- Urgency / 紧急度: {profile.get('time_urgency') or 'unknown'}",
            "",
        ]
    )


def render_project_obsidian_note(
    project: sqlite3.Row,
    lead: sqlite3.Row,
    score: sqlite3.Row,
    offer: sqlite3.Row,
    report: sqlite3.Row | None,
) -> str:
    approved = bool(project["client_approved_for_case_study"])
    fields = {
        "kb_type": "consulting_delivery",
        "consulting_type": "delivery_project",
        "lead_code": lead["lead_code"],
        "client_alias": lead["client_alias"],
        "offer_code": offer["code"],
        "classification": score["classification"],
        "case_study_approved": approved,
        "source_db_id": project["id"],
        "generated_at": now(),
        "pii_status": "anonymized",
        "managed_by": "codex",
        "review_state": "draft",
    }
    report_status = "available" if report else "not generated"
    return "\n".join(
        [
            frontmatter(fields),
            "",
            "# Consulting Delivery Preview / 咨询交付预览",
            "",
            f"- Project / 项目: {project['id']}",
            f"- Client / 客户: {lead['client_alias']}",
            f"- Offer / 服务包: {render_offer(offer)}",
            f"- Case study approved / 案例批准: {'yes' if approved else 'no'}",
            f"- Delivery report / 交付报告: {report_status}",
            "",
            "## Delivery checklist / 交付清单",
            "- Agenda / 议程",
            "- Pre-work checklist / 课前准备清单",
            "- Diagnosis framework / 诊断框架",
            "- Workflow map / 工作流地图",
            "- Recommended tools / 推荐工具",
            "- Implementation steps / 落地步骤",
            "- Follow-up report / 跟进报告",
            "",
            "## Case study gate / 案例门禁",
            "- Export case study only when `client_approved_for_case_study=true`.",
            "- 只有客户批准后才导出案例草稿。",
            "",
        ]
    )


def export_obsidian(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    assert_preview_output_dir(output_dir)
    conn = connect(Path(args.db))
    project = conn.execute("select * from delivery_projects where id = ?", (args.project_id,)).fetchone()
    if not project:
        raise SystemExit("Project not found / 未找到项目")
    lead = conn.execute("select * from leads where id = ?", (project["lead_id"],)).fetchone()
    score = latest_score(conn, lead["id"])
    offer = get_offer(conn, project["offer_code"])
    report = conn.execute(
        "select * from reports where project_id = ? order by created_at desc, id desc limit 1",
        (project["id"],),
    ).fetchone()

    lead_path = write_obsidian_note(
        output_dir,
        f"consulting-lead-{lead['lead_code']}.md",
        render_lead_obsidian_note(lead, score, offer),
    )
    project_path = write_obsidian_note(
        output_dir,
        f"consulting-project-{project['id']}.md",
        render_project_obsidian_note(project, lead, score, offer, report),
    )
    manifest_path = write_obsidian_manifest(
        output_dir,
        {
            "kind": "obsidian_preview_manifest",
            "project_id": project["id"],
            "lead_id": lead["id"],
            "lead_code": lead["lead_code"],
            "client_alias": lead["client_alias"],
            "offer_code": offer["code"],
            "pii_status": "anonymized",
            "live_vault_write": False,
            "generated_at": now(),
            "files": [
                {"type": "lead", "filename": Path(lead_path).name},
                {"type": "delivery_project", "filename": Path(project_path).name},
            ],
        },
    )
    print("Wrote Obsidian preview / 已写入 Obsidian 预览:")
    print(f"- {lead_path}")
    print(f"- {project_path}")
    print(f"- {manifest_path}")
    return 0


def export_json_snapshot(args: argparse.Namespace) -> int:
    out_path = Path(args.out)
    assert_preview_output_dir(out_path.parent)
    conn = connect(Path(args.db))
    conn.executescript(SCHEMA)
    ensure_discovery_call_columns(conn)
    ensure_status_metadata_columns(conn)
    project_rows = conn.execute(
        """
        select
          projects.*,
          leads.lead_code,
          leads.client_alias
        from delivery_projects projects
        join leads on leads.id = projects.lead_id
        order by projects.id
        """
    ).fetchall()
    payload = {
        "kind": "consulting_crm_snapshot",
        "generated_at": now(),
        "pii_status": "anonymized",
        "live_vault_write": False,
        "dashboard": dashboard_payload(conn),
        "leads": lead_rows_payload(conn),
        "projects": project_rows_payload(conn),
        "project_validations": [project_validation_payload(conn, row) for row in project_rows],
        "delivery_checklists": [delivery_checklist_snapshot_payload(conn, row) for row in project_rows],
        "followup_queues": [followup_queue_snapshot_payload(conn, row) for row in project_rows],
        "case_studies": case_studies_snapshot_payload(conn),
    }
    write_text(str(out_path), json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"Wrote JSON snapshot / 已写入 JSON 快照: {out_path}")
    return 0


def export_review_packet(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    assert_preview_output_dir(output_dir)
    conn = connect(Path(args.db))
    conn.executescript(SCHEMA)
    project = conn.execute(
        """
        select
          projects.*,
          leads.lead_code,
          leads.client_alias
        from delivery_projects projects
        join leads on leads.id = projects.lead_id
        where projects.id = ?
        """,
        (args.project_id,),
    ).fetchone()
    if not project:
        raise SystemExit("Project not found")

    proposal_count = 0
    if project["proposal_id"]:
        proposal_count = conn.execute(
            "select count(*) from proposals where id = ?",
            (project["proposal_id"],),
        ).fetchone()[0]
    report_count = conn.execute(
        "select count(*) from reports where project_id = ?",
        (project["id"],),
    ).fetchone()[0]
    discovery_count = conn.execute(
        "select count(*) from discovery_calls where project_id = ? or (project_id is null and lead_id = ?)",
        (project["id"], project["lead_id"]),
    ).fetchone()[0]
    checklist = {
        row["status"]: row["count"]
        for row in conn.execute(
            "select status, count(*) as count from delivery_checklists where project_id = ? group by status",
            (project["id"],),
        ).fetchall()
    }
    followups = followup_status_counts(conn, project["id"])
    checklist_count = sum(checklist.values())
    followup_count = sum(followups.values())
    ready = proposal_count > 0 and report_count > 0 and checklist_count > 0 and followup_count > 0
    remains = what_remains_payload(project_validation_payload(conn, project))

    obsidian_status: dict[str, Any] = {"status": "not_provided", "files": 0, "live_vault_write": False}
    if args.obsidian_manifest:
        manifest_path = Path(args.obsidian_manifest)
        if not manifest_path.exists():
            obsidian_status = {"status": "missing", "files": 0, "live_vault_write": False}
        else:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            obsidian_status = {
                "status": "ok",
                "files": len(manifest.get("files", [])),
                "live_vault_write": bool(manifest.get("live_vault_write", False)),
            }

    approved = "true" if project["client_approved_for_case_study"] else "false"
    obsidian_live = "true" if obsidian_status["live_vault_write"] else "false"
    packet_name = f"review-packet-project-{project['id']}.md"
    packet_path = output_dir / packet_name
    packet = "\n".join(
        [
            "# Consulting Review Packet / 咨询审核包",
            "",
            f"- Project / 项目: {project['id']}",
            f"- Lead / 线索: {project['lead_code']} ({project['client_alias']})",
            f"- Offer / 服务包: {project['offer_code']}",
            "- PII status / 隐私状态: anonymized",
            f"- case_study_approved={approved}",
            f"- ready_for_delivery={'true' if ready else 'false'}",
            "",
            "## Artifact status / 交付物状态",
            f"- proposal: {'ok' if proposal_count else 'missing'}",
            f"- delivery_report: {'ok' if report_count else 'missing'}",
            f"- discovery_calls: count={discovery_count}",
            (
                f"- delivery_checklist: count={checklist_count} "
                f"done={checklist.get('done', 0)} pending={checklist.get('pending', 0)}"
            ),
            (
                f"- followups: count={followup_count} "
                f"done={followups.get('done', 0)} planned={followups.get('planned', 0)}"
            ),
            (
                f"- obsidian_manifest: {obsidian_status['status']} files={obsidian_status['files']} "
                f"live_vault_write={obsidian_live}"
            ),
            "",
            "## Next review / 下一步审核",
            *[f"- next_action: {action}" for action in remains["next_actions"]],
            "- Review generated files locally before any manual copy into a live vault.",
            "- 先在本地审核生成文件，再决定是否人工复制到 live vault。",
            "",
        ]
    )
    write_text(str(packet_path), packet)
    manifest_path = write_review_packet_manifest(
        output_dir,
        {
            "kind": "review_packet_manifest",
            "project_id": project["id"],
            "lead_code": project["lead_code"],
            "client_alias": project["client_alias"],
            "pii_status": "anonymized",
            "live_vault_write": False,
            "ready_for_delivery": ready,
            "generated_at": now(),
            "files": [packet_name],
            "inputs": {
                "proposal": {"status": "ok" if proposal_count else "missing"},
                "delivery_report": {"status": "ok" if report_count else "missing"},
                "discovery_calls": {"count": discovery_count},
                "delivery_checklist": {
                    "count": checklist_count,
                    "done": checklist.get("done", 0),
                    "pending": checklist.get("pending", 0),
                },
                "followups": {
                    "count": followup_count,
                    "done": followups.get("done", 0),
                    "planned": followups.get("planned", 0),
                },
                "obsidian_manifest": obsidian_status,
            },
            "what_remains": remains,
        },
    )
    print("Wrote review packet / 已写入审核包:")
    print(f"- {packet_path}")
    print(f"- {manifest_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Tiny bilingual consulting CRM pilot")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init-db")
    p.add_argument("--db", default=str(DEFAULT_DB), help="SQLite DB path")
    p.set_defaults(func=init_db)

    p = sub.add_parser("import-leads")
    p.add_argument("--db", default=str(DEFAULT_DB), help="SQLite DB path")
    p.add_argument("--csv", required=True)
    p.add_argument("--lang", default="bilingual")
    p.set_defaults(func=import_leads)

    p = sub.add_parser("score-leads")
    p.add_argument("--db", default=str(DEFAULT_DB), help="SQLite DB path")
    p.add_argument("--lang", default="bilingual")
    p.set_defaults(func=score_leads)

    p = sub.add_parser("list-leads")
    p.add_argument("--db", default=str(DEFAULT_DB), help="SQLite DB path")
    p.add_argument("--format", choices=("text", "json"), default="text")
    p.set_defaults(func=list_leads)

    p = sub.add_parser("generate-proposal")
    p.add_argument("--db", default=str(DEFAULT_DB), help="SQLite DB path")
    p.add_argument("--lead-id", type=int, required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--lang", default="bilingual")
    p.set_defaults(func=generate_proposal)

    p = sub.add_parser("generate-delivery-report")
    p.add_argument("--db", default=str(DEFAULT_DB), help="SQLite DB path")
    p.add_argument("--project-id", type=int, required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--lang", default="bilingual")
    p.set_defaults(func=generate_delivery_report)

    p = sub.add_parser("record-discovery-call")
    p.add_argument("--db", default=str(DEFAULT_DB), help="SQLite DB path")
    p.add_argument("--lead-id", type=int, required=True)
    p.add_argument("--project-id", type=int)
    p.add_argument("--summary", required=True)
    p.add_argument("--current-state", default="")
    p.add_argument("--blockers", default="")
    p.add_argument("--desired-outcome", default="")
    p.add_argument("--next-step", default="")
    p.add_argument("--out", required=True)
    p.add_argument("--lang", default="bilingual")
    p.set_defaults(func=record_discovery_call)

    p = sub.add_parser("generate-delivery-checklist")
    p.add_argument("--db", default=str(DEFAULT_DB), help="SQLite DB path")
    p.add_argument("--project-id", type=int, required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--lang", default="bilingual")
    p.set_defaults(func=generate_delivery_checklist)

    p = sub.add_parser("list-delivery-checklist")
    p.add_argument("--db", default=str(DEFAULT_DB), help="SQLite DB path")
    p.add_argument("--project-id", type=int, required=True)
    p.add_argument("--format", choices=("text", "json"), default="text")
    p.set_defaults(func=list_delivery_checklist)

    p = sub.add_parser("mark-checklist-done")
    p.add_argument("--db", default=str(DEFAULT_DB), help="SQLite DB path")
    p.add_argument("--checklist-id", type=int, required=True)
    p.add_argument("--note", default="")
    p.set_defaults(func=mark_checklist_done)

    p = sub.add_parser("reopen-checklist-item")
    p.add_argument("--db", default=str(DEFAULT_DB), help="SQLite DB path")
    p.add_argument("--checklist-id", type=int, required=True)
    p.set_defaults(func=reopen_checklist_item)

    p = sub.add_parser("generate-followup")
    p.add_argument("--db", default=str(DEFAULT_DB), help="SQLite DB path")
    p.add_argument("--project-id", type=int, required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--lang", default="bilingual")
    p.set_defaults(func=generate_followup)

    p = sub.add_parser("list-followups")
    p.add_argument("--db", default=str(DEFAULT_DB), help="SQLite DB path")
    p.add_argument("--project-id", type=int, required=True)
    p.add_argument("--format", choices=("text", "json"), default="text")
    p.set_defaults(func=list_followups)

    p = sub.add_parser("mark-followup-done")
    p.add_argument("--db", default=str(DEFAULT_DB), help="SQLite DB path")
    p.add_argument("--followup-id", type=int, required=True)
    p.add_argument("--note", default="")
    p.set_defaults(func=mark_followup_done)

    p = sub.add_parser("reopen-followup")
    p.add_argument("--db", default=str(DEFAULT_DB), help="SQLite DB path")
    p.add_argument("--followup-id", type=int, required=True)
    p.set_defaults(func=reopen_followup)

    p = sub.add_parser("list-projects")
    p.add_argument("--db", default=str(DEFAULT_DB), help="SQLite DB path")
    p.add_argument("--format", choices=("text", "json"), default="text")
    p.set_defaults(func=list_projects)

    p = sub.add_parser("show-project")
    p.add_argument("--db", default=str(DEFAULT_DB), help="SQLite DB path")
    p.add_argument("--project-id", type=int, required=True)
    p.add_argument("--format", choices=("text", "json"), default="text")
    p.set_defaults(func=show_project)

    p = sub.add_parser("dashboard")
    p.add_argument("--db", default=str(DEFAULT_DB), help="SQLite DB path")
    p.add_argument("--format", choices=("text", "json"), default="text")
    p.set_defaults(func=dashboard)

    p = sub.add_parser("validate-project")
    p.add_argument("--db", default=str(DEFAULT_DB), help="SQLite DB path")
    p.add_argument("--project-id", type=int, required=True)
    p.add_argument("--format", choices=("text", "json"), default="text")
    p.set_defaults(func=validate_project)

    p = sub.add_parser("what-remains")
    p.add_argument("--db", default=str(DEFAULT_DB), help="SQLite DB path")
    p.add_argument("--project-id", type=int, required=True)
    p.add_argument("--format", choices=("text", "json"), default="text")
    p.set_defaults(func=what_remains)

    p = sub.add_parser("approve-case-study")
    p.add_argument("--db", default=str(DEFAULT_DB), help="SQLite DB path")
    p.add_argument("--project-id", type=int, required=True)
    p.add_argument("--approved-by", default="local-operator")
    p.add_argument("--format", choices=("text", "json"), default="text")
    p.set_defaults(func=approve_case_study)

    p = sub.add_parser("revoke-case-study-approval")
    p.add_argument("--db", default=str(DEFAULT_DB), help="SQLite DB path")
    p.add_argument("--project-id", type=int, required=True)
    p.add_argument("--format", choices=("text", "json"), default="text")
    p.set_defaults(func=revoke_case_study_approval)

    p = sub.add_parser("export-case-study")
    p.add_argument("--db", default=str(DEFAULT_DB), help="SQLite DB path")
    p.add_argument("--project-id", type=int, required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--lang", default="bilingual")
    p.add_argument("--format", choices=("text", "json"), default="text")
    p.set_defaults(func=export_case_study)

    p = sub.add_parser("export-obsidian")
    p.add_argument("--db", default=str(DEFAULT_DB), help="SQLite DB path")
    p.add_argument("--project-id", type=int, required=True)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--lang", default="bilingual")
    p.set_defaults(func=export_obsidian)

    p = sub.add_parser("export-json-snapshot")
    p.add_argument("--db", default=str(DEFAULT_DB), help="SQLite DB path")
    p.add_argument("--out", required=True)
    p.set_defaults(func=export_json_snapshot)

    p = sub.add_parser("export-review-packet")
    p.add_argument("--db", default=str(DEFAULT_DB), help="SQLite DB path")
    p.add_argument("--project-id", type=int, required=True)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--obsidian-manifest")
    p.set_defaults(func=export_review_packet)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except SystemExit:
        raise
    except Exception as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    raise SystemExit(main())
