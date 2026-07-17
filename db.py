"""FastGrants data layer — SQLite, grant / EU-funds lifecycle.

Core entities model the full administrative lifecycle of a grant programme:

  calls          funding calls / programmes (budget, dates, status)
  applicants     organisations that apply
  applications   intake — submitted → under review → approved / rejected
  documents      supporting files attached to an application
  grants         approved applications become grant agreements (awards)
  milestones     deliverables per grant, each carrying a disbursement tranche
  reports        beneficiary periodic progress + financial reports
  activity       lightweight audit trail across entities

The module is deliberately administrative: it helps a funding body *run*
grants (intake, award, disburse, monitor) — it does not score or rank the
science. All amounts are EUR-denominated for the synthetic demo.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

DB_PATH = os.getenv("FASTGRANTS_DB") or str(Path(__file__).parent / "fastgrants.sqlite")

# "Today" for the synthetic world — keeps due-dates / overdue states stable.
NOW = datetime(2026, 7, 16, 12, 0, 0)

CALL_STATUSES = ["Draft", "Open", "Evaluation", "Closed"]
APP_STATUSES = ["Draft", "Submitted", "Under Review", "Approved", "Rejected"]
APP_OPEN_STATUSES = ["Submitted", "Under Review"]
GRANT_STATUSES = ["Active", "Completed", "Terminated"]
MILESTONE_STATUSES = ["Pending", "In Progress", "Completed", "Overdue"]
REPORT_STATUSES = ["Draft", "Submitted", "Approved", "Rejected"]
DOC_STATUSES = ["Missing", "Received", "Verified"]
ORG_TYPES = ["SME", "Large Enterprise", "University", "Research Org", "NGO", "Public Body"]
DOC_TYPES = ["Application form", "Budget", "Legal entity", "Bank details",
             "Declaration of honour", "Work plan", "Financial statement"]


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


@contextmanager
def cursor():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def db_exists() -> bool:
    p = Path(DB_PATH)
    return p.exists() and p.stat().st_size > 0


def rows(sql, params=()):
    with cursor() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def one(sql, params=()):
    with cursor() as conn:
        r = conn.execute(sql, params).fetchone()
        return dict(r) if r else None


def scalar(sql, params=()):
    with cursor() as conn:
        r = conn.execute(sql, params).fetchone()
        return r[0] if r else None


SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    programme     TEXT,
    description   TEXT,
    budget_total  REAL NOT NULL DEFAULT 0,
    currency      TEXT NOT NULL DEFAULT 'EUR',
    opens_on      TEXT,
    closes_on     TEXT,
    status        TEXT NOT NULL DEFAULT 'Open',
    created       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS applicants (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    org_type      TEXT,
    country       TEXT,
    contact_name  TEXT,
    contact_email TEXT,
    created       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS applications (
    id                INTEGER PRIMARY KEY,
    ref               TEXT,
    call_id           INTEGER REFERENCES calls(id),
    applicant_id      INTEGER REFERENCES applicants(id),
    title             TEXT NOT NULL,
    summary           TEXT,
    amount_requested  REAL NOT NULL DEFAULT 0,
    status            TEXT NOT NULL DEFAULT 'Submitted',
    score             REAL,
    submitted_on      TEXT,
    decided_on        TEXT,
    created           TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    id             INTEGER PRIMARY KEY,
    application_id INTEGER NOT NULL REFERENCES applications(id),
    name           TEXT NOT NULL,
    doc_type       TEXT,
    status         TEXT NOT NULL DEFAULT 'Received'
);
CREATE TABLE IF NOT EXISTS grants (
    id             INTEGER PRIMARY KEY,
    agreement_ref  TEXT NOT NULL,
    application_id INTEGER REFERENCES applications(id),
    amount_awarded REAL NOT NULL DEFAULT 0,
    currency       TEXT NOT NULL DEFAULT 'EUR',
    start_date     TEXT,
    end_date       TEXT,
    status         TEXT NOT NULL DEFAULT 'Active',
    created        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS milestones (
    id            INTEGER PRIMARY KEY,
    grant_id      INTEGER NOT NULL REFERENCES grants(id),
    title         TEXT NOT NULL,
    due_date      TEXT,
    amount        REAL NOT NULL DEFAULT 0,     -- disbursement tranche
    status        TEXT NOT NULL DEFAULT 'Pending',
    disbursed     INTEGER NOT NULL DEFAULT 0,
    disbursed_on  TEXT
);
CREATE TABLE IF NOT EXISTS reports (
    id                INTEGER PRIMARY KEY,
    grant_id          INTEGER NOT NULL REFERENCES grants(id),
    milestone_id      INTEGER REFERENCES milestones(id),
    period            TEXT,
    progress_summary  TEXT,
    amount_claimed    REAL NOT NULL DEFAULT 0,
    amount_disbursed  REAL NOT NULL DEFAULT 0,
    status            TEXT NOT NULL DEFAULT 'Submitted',
    submitted_on      TEXT,
    created           TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS activity (
    id            INTEGER PRIMARY KEY,
    entity_type   TEXT NOT NULL,     -- 'application' | 'grant'
    entity_id     INTEGER NOT NULL,
    action        TEXT NOT NULL,
    actor         TEXT,
    created       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_messages (
    id            INTEGER PRIMARY KEY,
    thread_id     TEXT NOT NULL,
    role          TEXT NOT NULL,
    content       TEXT NOT NULL,
    created       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_app_call    ON applications(call_id);
CREATE INDEX IF NOT EXISTS idx_app_status  ON applications(status);
CREATE INDEX IF NOT EXISTS idx_doc_app     ON documents(application_id);
CREATE INDEX IF NOT EXISTS idx_ms_grant    ON milestones(grant_id);
CREATE INDEX IF NOT EXISTS idx_rep_grant   ON reports(grant_id);
CREATE INDEX IF NOT EXISTS idx_act_entity  ON activity(entity_type, entity_id);
"""


def init_schema():
    with cursor() as conn:
        conn.executescript(SCHEMA)


# --- formatting -------------------------------------------------------------

def eur(amount) -> str:
    try:
        return f"€{float(amount or 0):,.0f}"
    except (TypeError, ValueError):
        return "€0"


def _parse(ts: str | None):
    if not ts:
        return None
    try:
        return datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            return datetime.strptime(ts[:10], "%Y-%m-%d")
        except ValueError:
            return None


def due_state(due_date: str | None, done: bool = False) -> dict:
    """Badge info for a milestone/report deadline vs NOW."""
    d = _parse(due_date)
    if done:
        return {"label": "Disbursed", "tone": "ok"}
    if not d:
        return {"label": "No date", "tone": "neutral"}
    days = (d - NOW).days
    if days < 0:
        return {"label": f"Overdue {-days}d", "tone": "breach"}
    if days <= 30:
        return {"label": f"Due in {days}d", "tone": "warn"}
    return {"label": f"Due in {days}d", "tone": "ok"}


# --- aggregate reads --------------------------------------------------------

def kpis() -> dict:
    total_budget = scalar("SELECT COALESCE(SUM(budget_total),0) FROM calls WHERE status!='Draft'") or 0
    allocated = scalar("SELECT COALESCE(SUM(amount_awarded),0) FROM grants WHERE status IN ('Active','Completed')") or 0
    disbursed = scalar("SELECT COALESCE(SUM(amount),0) FROM milestones WHERE disbursed=1") or 0
    active_grants = scalar("SELECT COUNT(*) FROM grants WHERE status='Active'") or 0
    open_apps = scalar(
        f"SELECT COUNT(*) FROM applications WHERE status IN ({_ph(APP_OPEN_STATUSES)})",
        tuple(APP_OPEN_STATUSES)) or 0
    decided = scalar("SELECT COUNT(*) FROM applications WHERE status IN ('Approved','Rejected')") or 0
    approved = scalar("SELECT COUNT(*) FROM applications WHERE status='Approved'") or 0
    return {
        "total_budget": total_budget,
        "allocated": allocated,
        "disbursed": disbursed,
        "committed_pct": round(100 * allocated / total_budget) if total_budget else 0,
        "disbursed_pct": round(100 * disbursed / allocated) if allocated else 0,
        "active_grants": active_grants,
        "open_apps": open_apps,
        "approval_rate": round(100 * approved / decided) if decided else 0,
        "beneficiaries": scalar("SELECT COUNT(DISTINCT application_id) FROM grants") or 0,
    }


def _ph(seq):
    return ",".join("?" * len(seq))


def apps_by_status() -> dict:
    return {r["status"]: r["n"]
            for r in rows("SELECT status, COUNT(*) n FROM applications GROUP BY status")}


def budget_by_call() -> list[dict]:
    return rows(
        """SELECT c.name, c.budget_total,
                  COALESCE((SELECT SUM(g.amount_awarded) FROM grants g
                            JOIN applications a ON a.id=g.application_id
                            WHERE a.call_id=c.id AND g.status IN ('Active','Completed')),0) allocated,
                  COALESCE((SELECT SUM(m.amount) FROM milestones m
                            JOIN grants g ON g.id=m.grant_id
                            JOIN applications a ON a.id=g.application_id
                            WHERE a.call_id=c.id AND m.disbursed=1),0) disbursed
           FROM calls c WHERE c.status!='Draft' ORDER BY c.budget_total DESC""")


# --- calls ------------------------------------------------------------------

def calls() -> list[dict]:
    return rows(
        """SELECT c.*,
                  (SELECT COUNT(*) FROM applications a WHERE a.call_id=c.id) app_n,
                  (SELECT COUNT(*) FROM applications a WHERE a.call_id=c.id AND a.status='Approved') awarded_n
           FROM calls c ORDER BY c.closes_on DESC""")


def call(cid: int):
    return one("SELECT * FROM calls WHERE id=?", (cid,))


def applications_for_call(cid: int):
    return rows(
        """SELECT a.*, ap.name applicant FROM applications a
           LEFT JOIN applicants ap ON ap.id=a.applicant_id
           WHERE a.call_id=? ORDER BY a.amount_requested DESC""", (cid,))


# --- applications -----------------------------------------------------------

def applications(status="All", call_id=None):
    where, params = [], []
    if status == "Open":
        where.append(f"a.status IN ({_ph(APP_OPEN_STATUSES)})")
        params += APP_OPEN_STATUSES
    elif status != "All":
        where.append("a.status=?")
        params.append(status)
    if call_id:
        where.append("a.call_id=?")
        params.append(call_id)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    return rows(
        f"""SELECT a.*, ap.name applicant, ap.org_type, ap.country, c.name call_name
            FROM applications a
            LEFT JOIN applicants ap ON ap.id=a.applicant_id
            LEFT JOIN calls c ON c.id=a.call_id
            {clause} ORDER BY a.submitted_on DESC, a.created DESC LIMIT 300""", tuple(params))


def application(aid: int):
    return one(
        """SELECT a.*, ap.name applicant, ap.org_type, ap.country, ap.contact_name, ap.contact_email,
                  c.name call_name, c.programme
           FROM applications a
           LEFT JOIN applicants ap ON ap.id=a.applicant_id
           LEFT JOIN calls c ON c.id=a.call_id
           WHERE a.id=?""", (aid,))


def documents_for(aid: int):
    return rows("SELECT * FROM documents WHERE application_id=? ORDER BY id", (aid,))


def grant_for_application(aid: int):
    return one("SELECT * FROM grants WHERE application_id=?", (aid,))


def activity_for(entity_type: str, entity_id: int):
    return rows("SELECT * FROM activity WHERE entity_type=? AND entity_id=? ORDER BY created DESC",
                (entity_type, entity_id))


def _log(entity_type, entity_id, action, actor="Programme Officer"):
    with cursor() as conn:
        conn.execute(
            "INSERT INTO activity(entity_type,entity_id,action,actor,created) VALUES (?,?,?,?,datetime('now'))",
            (entity_type, entity_id, action, actor))


# --- application workflow ---------------------------------------------------

APP_TRANSITIONS = {
    "start_review": ("Submitted", "Under Review", "Moved to <strong>Under Review</strong>"),
    "approve": ("Under Review", "Approved", "Application <strong>Approved</strong>"),
    "reject": ("Under Review", "Rejected", "Application <strong>Rejected</strong>"),
    "reopen": ("Rejected", "Under Review", "Re-opened for <strong>Review</strong>"),
}


def advance_application(aid: int, action: str) -> dict | None:
    tr = APP_TRANSITIONS.get(action)
    if not tr:
        return None
    frm, to, msg = tr
    app = application(aid)
    if not app or app["status"] != frm:
        return {"ok": False, "error": f"Cannot {action} an application that is {app['status'] if app else 'missing'}."}
    with cursor() as conn:
        conn.execute("UPDATE applications SET status=?, decided_on=CASE WHEN ? IN ('Approved','Rejected') "
                     "THEN datetime('now') ELSE decided_on END WHERE id=?", (to, to, aid))
    _log("application", aid, msg)
    if to == "Approved":
        gid = _create_grant_from_application(aid)
        return {"ok": True, "status": to, "grant_id": gid}
    return {"ok": True, "status": to}


def _create_grant_from_application(aid: int) -> int:
    app = application(aid)
    if not app:
        return 0
    existing = grant_for_application(aid)
    if existing:
        return existing["id"]
    amount = app["amount_requested"] or 0
    ref = f"GA-{NOW.year}-{aid:04d}"
    start = NOW.strftime("%Y-%m-%d")
    end = f"{NOW.year + 2}-{NOW.month:02d}-{NOW.day:02d}"
    with cursor() as conn:
        cur = conn.execute(
            """INSERT INTO grants(agreement_ref,application_id,amount_awarded,currency,start_date,end_date,status,created)
               VALUES (?,?,?,?,?,?, 'Active', datetime('now'))""",
            (ref, aid, amount, "EUR", start, end))
        gid = cur.lastrowid
        # split the award into three disbursement tranches (pre-financing / interim / final)
        tranches = [("Pre-financing (kick-off)", 0.4, 30),
                    ("Interim report & payment", 0.4, 365),
                    ("Final report & balance", 0.2, 700)]
        from datetime import timedelta
        for title, frac, days in tranches:
            due = (NOW + timedelta(days=days)).strftime("%Y-%m-%d")
            conn.execute(
                """INSERT INTO milestones(grant_id,title,due_date,amount,status,disbursed)
                   VALUES (?,?,?,?, 'Pending', 0)""",
                (gid, title, due, round(amount * frac)))
    _log("grant", gid, f"Grant agreement <strong>{ref}</strong> created ({eur(amount)})")
    return gid


# --- grants -----------------------------------------------------------------

def grants(status="All"):
    where, params = "", ()
    if status != "All":
        where, params = "WHERE g.status=?", (status,)
    return rows(
        f"""SELECT g.*, ap.name beneficiary, a.title project,
                   (SELECT COALESCE(SUM(amount),0) FROM milestones m WHERE m.grant_id=g.id AND m.disbursed=1) disbursed,
                   (SELECT COUNT(*) FROM milestones m WHERE m.grant_id=g.id) ms_n,
                   (SELECT COUNT(*) FROM milestones m WHERE m.grant_id=g.id AND m.disbursed=1) ms_done
            FROM grants g
            LEFT JOIN applications a ON a.id=g.application_id
            LEFT JOIN applicants ap ON ap.id=a.applicant_id
            {where} ORDER BY g.created DESC""", params)


def grant(gid: int):
    return one(
        """SELECT g.*, ap.name beneficiary, ap.org_type, ap.country, a.title project, a.summary, c.name call_name
           FROM grants g
           LEFT JOIN applications a ON a.id=g.application_id
           LEFT JOIN applicants ap ON ap.id=a.applicant_id
           LEFT JOIN calls c ON c.id=a.call_id
           WHERE g.id=?""", (gid,))


def milestones_for(gid: int):
    return rows("SELECT * FROM milestones WHERE grant_id=? ORDER BY due_date", (gid,))


def reports_for(gid: int):
    return rows(
        """SELECT r.*, m.title milestone FROM reports r
           LEFT JOIN milestones m ON m.id=r.milestone_id
           WHERE r.grant_id=? ORDER BY r.submitted_on DESC, r.created DESC""", (gid,))


def disburse_milestone(mid: int) -> bool:
    m = one("SELECT * FROM milestones WHERE id=?", (mid,))
    if not m or m["disbursed"]:
        return False
    with cursor() as conn:
        conn.execute("UPDATE milestones SET disbursed=1, status='Completed', disbursed_on=datetime('now') WHERE id=?",
                     (mid,))
    _log("grant", m["grant_id"], f"Disbursed tranche <strong>{m['title']}</strong> ({eur(m['amount'])})", actor="Finance")
    return True


# --- reports ----------------------------------------------------------------

def reports(status="All"):
    where, params = "", ()
    if status != "All":
        where, params = "WHERE r.status=?", (status,)
    return rows(
        f"""SELECT r.*, g.agreement_ref, ap.name beneficiary, m.title milestone
            FROM reports r
            LEFT JOIN grants g ON g.id=r.grant_id
            LEFT JOIN applications a ON a.id=g.application_id
            LEFT JOIN applicants ap ON ap.id=a.applicant_id
            LEFT JOIN milestones m ON m.id=r.milestone_id
            {where} ORDER BY r.submitted_on DESC, r.created DESC LIMIT 300""", params)


def report(rid: int):
    return one(
        """SELECT r.*, g.agreement_ref, g.id grant_id, ap.name beneficiary, m.title milestone, m.amount ms_amount
           FROM reports r
           LEFT JOIN grants g ON g.id=r.grant_id
           LEFT JOIN applications a ON a.id=g.application_id
           LEFT JOIN applicants ap ON ap.id=a.applicant_id
           LEFT JOIN milestones m ON m.id=r.milestone_id
           WHERE r.id=?""", (rid,))


def review_report(rid: int, action: str) -> dict | None:
    """approve → disburse linked milestone; reject → mark rejected."""
    r = report(rid)
    if not r or r["status"] not in ("Submitted", "Draft"):
        return {"ok": False, "error": "Only submitted reports can be reviewed."}
    if action == "approve":
        disbursed = r["ms_amount"] or r["amount_claimed"] or 0
        with cursor() as conn:
            conn.execute("UPDATE reports SET status='Approved', amount_disbursed=? WHERE id=?", (disbursed, rid))
        if r["milestone_id"]:
            disburse_milestone(r["milestone_id"])
        _log("grant", r["grant_id"], f"Approved {r['period']} report — disbursed {eur(disbursed)}", actor="Finance")
        return {"ok": True, "status": "Approved"}
    if action == "reject":
        with cursor() as conn:
            conn.execute("UPDATE reports SET status='Rejected' WHERE id=?", (rid,))
        _log("grant", r["grant_id"], f"Rejected {r['period']} report — clarification requested")
        return {"ok": True, "status": "Rejected"}
    return None
