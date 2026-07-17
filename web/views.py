"""Center-pane page renderers for FastGrants."""
from __future__ import annotations

from fasthtml.common import (
    Div, H1, H3, H4, P, Span, A, Table, Thead, Tbody, Tr, Th, Td, Ul, Li,
    Strong, NotStr, Form, Input, Button,
)

import db
from web.layout import kpi_card
from web import charts


def _pill(text, kind=""):
    return Span(text, cls="pill " + (kind or str(text)).lower().replace(" ", "").replace("/", ""))


def _due(state):
    return Span(state["label"], cls=f"sla {state['tone']}")


def _title(title, sub="", *actions):
    return Div(Div(H1(title), P(sub, cls="sub") if sub else None),
               Div(*actions) if actions else None, cls="page-title")


def _ago(ts):
    return (ts or "—")[:10]


def _bar(pct, kind=""):
    pct = max(0, min(100, pct or 0))
    return Div(Div(cls=f"bar-fill {kind}", style=f"width:{pct}%;"), cls="bar-wrap")


# ---------- dashboard -------------------------------------------------------

def dashboard():
    k = db.kpis()
    by_call = db.budget_by_call()
    by_status = db.apps_by_status()
    bc, bs = charts.budget_chart(by_call), charts.pipeline_chart(by_status, db.APP_STATUSES)
    gauge = charts.disbursement_gauge(k["allocated"], k["disbursed"])

    # active grants needing attention: overdue milestones
    overdue = db.rows(
        """SELECT m.*, g.agreement_ref, ap.name beneficiary FROM milestones m
           JOIN grants g ON g.id=m.grant_id
           LEFT JOIN applications a ON a.id=g.application_id
           LEFT JOIN applicants ap ON ap.id=a.applicant_id
           WHERE m.disbursed=0 AND m.due_date < ? ORDER BY m.due_date LIMIT 8""", (db.NOW.strftime("%Y-%m-%d"),))
    overdue_tbl = Table(
        Thead(Tr(Th("Agreement"), Th("Beneficiary"), Th("Milestone"), Th("Tranche", cls="num"), Th("Due"))),
        Tbody(*[Tr(Td(A(m["agreement_ref"], href=f"/grants/{m['grant_id']}")),
                   Td(m["beneficiary"] or "—"), Td(m["title"]),
                   Td(db.eur(m["amount"]), cls="num"), Td(_due(db.due_state(m["due_date"]))))
                for m in overdue] or [Tr(Td("No overdue milestones 🎉", colspan="5"))]), cls="tbl")

    return (
        _title("Programme Dashboard", "Budget, pipeline & disbursement — fully synthetic demo data."),
        Div(kpi_card("Programme budget", db.eur(k["total_budget"]), f"{k['committed_pct']}% committed"),
            kpi_card("Allocated (awarded)", db.eur(k["allocated"]), f"{k['active_grants']} active grants", tone="ok"),
            kpi_card("Disbursed", db.eur(k["disbursed"]), f"{k['disbursed_pct']}% of allocated", tone="gold"),
            kpi_card("Open applications", k["open_apps"], f"{k['approval_rate']}% approval rate", tone="warn"),
            cls="kpi-grid"),
        Div(Div(Div(H3("Budget: allocated vs disbursed by call"), cls="card-header"), *bc, cls="card"),
            Div(Div(H3("Disbursement rate"), cls="card-header"), *gauge, cls="card"), cls="grid-2"),
        Div(Div(H3("Application pipeline"), cls="card-header"), *bs, cls="card"),
        Div(Div(H3("Overdue milestones — act now"), cls="card-header"), overdue_tbl, cls="card"),
    )


# ---------- calls -----------------------------------------------------------

def calls_list():
    cs = db.calls()
    tbl = Table(
        Thead(Tr(Th("Call / Programme"), Th("Budget", cls="num"), Th("Opens"), Th("Closes"),
                 Th("Apps", cls="num"), Th("Awarded", cls="num"), Th("Status"))),
        Tbody(*[Tr(
            Td(A(Strong(c["name"]), href=f"/calls/{c['id']}"),
               Div(c["programme"] or "", style="color:var(--text-mute);font-size:12px;")),
            Td(db.eur(c["budget_total"]), cls="num"),
            Td(_ago(c["opens_on"])), Td(_ago(c["closes_on"])),
            Td(str(c["app_n"]), cls="num"), Td(str(c["awarded_n"]), cls="num"),
            Td(_pill(c["status"]))) for c in cs]), cls="tbl")
    return _title("Calls & Programmes", f"{len(cs)} funding calls"), Div(tbl, cls="card")


def call_detail(cid):
    c = db.call(cid)
    if not c:
        return _title("Call not found"), P("No such call.")
    apps = db.applications_for_call(cid)
    awarded = sum(1 for a in apps if a["status"] == "Approved")
    requested = sum(a["amount_requested"] or 0 for a in apps)
    info = Div(Div(H3("Call details"), _pill(c["status"]), cls="card-header"),
               Div(Span("Programme", cls="k"), Span(c["programme"] or "—"),
                   Span("Budget", cls="k"), Span(db.eur(c["budget_total"])),
                   Span("Opens", cls="k"), Span(_ago(c["opens_on"])),
                   Span("Closes", cls="k"), Span(_ago(c["closes_on"])),
                   Span("Applications", cls="k"), Span(f"{len(apps)} ({awarded} approved)"),
                   Span("Total requested", cls="k"), Span(db.eur(requested)),
                   cls="kv"),
               P(c["description"] or "", style="margin-top:12px;color:var(--text-dim);"), cls="card")
    tbl = Table(
        Thead(Tr(Th("Ref"), Th("Project"), Th("Applicant"), Th("Requested", cls="num"),
                 Th("Score", cls="num"), Th("Status"))),
        Tbody(*[Tr(Td(A(a["ref"], href=f"/applications/{a['id']}")),
                   Td(A(a["title"][:40], href=f"/applications/{a['id']}")),
                   Td(a["applicant"] or "—"), Td(db.eur(a["amount_requested"]), cls="num"),
                   Td(str(a["score"] or "—"), cls="num"), Td(_pill(a["status"])))
                for a in apps] or [Tr(Td("No applications yet.", colspan="6"))]), cls="tbl")
    return (_title(c["name"], c["programme"] or "", A("← All calls", href="/calls", cls="btn")),
            info, Div(Div(H3("Applications"), cls="card-header"), tbl, cls="card"))


# ---------- applications ----------------------------------------------------

def applications_list(status="All"):
    seg = Div(*[A(s, href=f"/applications?status={s}", cls="" + ("active" if status == s else ""))
                for s in ["All", "Open", *db.APP_STATUSES]], cls="seg")
    apps = db.applications(status)
    tbl = Table(
        Thead(Tr(Th("Ref"), Th("Project"), Th("Applicant"), Th("Call"), Th("Requested", cls="num"),
                 Th("Score", cls="num"), Th("Status"), Th("Submitted"))),
        Tbody(*[Tr(
            Td(A(a["ref"], href=f"/applications/{a['id']}")),
            Td(A(a["title"][:38], href=f"/applications/{a['id']}")),
            Td(a["applicant"] or "—"), Td((a["call_name"] or "—").split(" — ")[0][:22]),
            Td(db.eur(a["amount_requested"]), cls="num"), Td(str(a["score"] or "—"), cls="num"),
            Td(_pill(a["status"])), Td(_ago(a["submitted_on"]), style="color:var(--text-mute);"),
        ) for a in apps] or [Tr(Td("No applications match.", colspan="8"))]), cls="tbl")
    return _title("Applications", f"{len(apps)} shown"), seg, Div(tbl, cls="card")


def _workflow_buttons(app):
    """Status-appropriate action buttons that POST and swap the detail body."""
    aid = app["id"]
    actions = []
    st = app["status"]
    if st == "Submitted":
        actions.append(("start_review", "▶ Start review", "primary"))
    elif st == "Under Review":
        actions.append(("approve", "✔ Approve & award", "ok"))
        actions.append(("reject", "✗ Reject", "danger"))
    elif st == "Rejected":
        actions.append(("reopen", "↺ Re-open review", ""))
    btns = [Button(label, cls=f"btn {cls}",
                   **{"hx-post": f"/applications/{aid}/{action}",
                      "hx-target": "#app-main", "hx-swap": "innerHTML"}) for action, label, cls in actions]
    return Div(*btns, style="display:flex;gap:8px;flex-wrap:wrap;") if btns else None


def application_main(aid):
    a = db.application(aid)
    if not a:
        return Div(P("No such application."))
    docs = db.documents_for(aid)
    acts = db.activity_for("application", aid)
    g = db.grant_for_application(aid)

    doc_tbl = Table(
        Thead(Tr(Th("Document"), Th("Type"), Th("Status"))),
        Tbody(*[Tr(Td(d["name"]), Td(d["doc_type"] or "—"), Td(_pill(d["status"])))
                for d in docs] or [Tr(Td("No documents.", colspan="3"))]), cls="tbl")

    grant_block = None
    if g:
        grant_block = Div(Div(H3("Grant agreement"), _pill(g["status"]), cls="card-header"),
                          P(NotStr(f"Awarded <strong>{db.eur(g['amount_awarded'])}</strong> — "
                                   f"agreement <a href='/grants/{g['id']}'>{g['agreement_ref']}</a>.")), cls="card")

    left = Div(
        Div(Div(H3("Project summary"), cls="card-header"),
            P(a["summary"] or "", style="color:var(--text-dim);line-height:1.6;"), cls="card"),
        Div(Div(H3(f"Supporting documents ({len(docs)})"), cls="card-header"), doc_tbl, cls="card"),
        grant_block)

    wf = _workflow_buttons(a)
    info = Div(Div(H3("Application"), _pill(a["status"]), cls="card-header"),
               Div(Span("Reference", cls="k"), Span(a["ref"] or "—"),
                   Span("Applicant", cls="k"), Span(a["applicant"] or "—"),
                   Span("Org type", cls="k"), Span(a["org_type"] or "—"),
                   Span("Country", cls="k"), Span(a["country"] or "—"),
                   Span("Call", cls="k"), Span(a["call_name"] or "—"),
                   Span("Requested", cls="k"), Span(db.eur(a["amount_requested"])),
                   Span("Score", cls="k"), Span(str(a["score"] or "—")),
                   Span("Submitted", cls="k"), Span(_ago(a["submitted_on"])),
                   Span("Contact", cls="k"), Span(a["contact_email"] or "—"),
                   cls="kv"),
               Div(wf, style="margin-top:14px;") if wf else None, cls="card")
    timeline = Ul(*[Li(Div(Strong(NotStr(x["action"])), " ", Span(x["actor"] or "", style="color:var(--text-mute);")),
                       Div(_ago(x["created"]), cls="when")) for x in acts] or [Li("No activity yet.")], cls="timeline")
    right = Div(info, Div(Div(H3("Activity"), cls="card-header"), timeline, cls="card"))
    return Div(left, right, cls="detail-grid")


def application_detail(aid):
    a = db.application(aid)
    if not a:
        return _title("Application not found"), P("No such application.")
    return (_title(a["title"], f"{a['ref']} · {a['applicant']}", A("← All applications", href="/applications", cls="btn")),
            Div(application_main(aid), id="app-main"))


# ---------- grants ----------------------------------------------------------

def grants_list(status="All"):
    seg = Div(*[A(s, href=f"/grants?status={s}", cls="" + ("active" if status == s else ""))
                for s in ["All", *db.GRANT_STATUSES]], cls="seg")
    gs = db.grants(status)
    tbl = Table(
        Thead(Tr(Th("Agreement"), Th("Beneficiary"), Th("Project"), Th("Awarded", cls="num"),
                 Th("Disbursed", cls="num"), Th("Progress"), Th("Status"))),
        Tbody(*[Tr(
            Td(A(g["agreement_ref"], href=f"/grants/{g['id']}")),
            Td(g["beneficiary"] or "—"), Td((g["project"] or "—")[:32]),
            Td(db.eur(g["amount_awarded"]), cls="num"), Td(db.eur(g["disbursed"]), cls="num"),
            Td(_bar(round(100 * (g["disbursed"] or 0) / g["amount_awarded"]) if g["amount_awarded"] else 0, "gold"),
               style="min-width:120px;"),
            Td(_pill(g["status"]))) for g in gs] or [Tr(Td("No grants yet.", colspan="7"))]), cls="tbl")
    total_awarded = sum(g["amount_awarded"] or 0 for g in gs)
    total_disb = sum(g["disbursed"] or 0 for g in gs)
    return (_title("Grants & Agreements",
                   f"{len(gs)} agreements · {db.eur(total_awarded)} awarded · {db.eur(total_disb)} disbursed"),
            seg, Div(tbl, cls="card"))


def grant_main(gid):
    g = db.grant(gid)
    if not g:
        return Div(P("No such grant."))
    ms = db.milestones_for(gid)
    reps = db.reports_for(gid)
    disbursed = sum(m["amount"] for m in ms if m["disbursed"])

    ms_rows = []
    for m in ms:
        act = None
        if not m["disbursed"]:
            act = Button("💶 Disburse", cls="btn sm gold",
                         **{"hx-post": f"/grants/{gid}/milestones/{m['id']}/disburse",
                            "hx-target": "#grant-main", "hx-swap": "innerHTML"})
        else:
            act = Span("Paid " + _ago(m["disbursed_on"]), style="color:var(--text-mute);font-size:12px;")
        ms_rows.append(Tr(Td(m["title"]), Td(db.eur(m["amount"]), cls="num"),
                          Td(_due(db.due_state(m["due_date"], bool(m["disbursed"])))),
                          Td(_pill(m["status"])), Td(act)))
    ms_tbl = Table(Thead(Tr(Th("Milestone / tranche"), Th("Amount", cls="num"), Th("Due"), Th("Status"), Th(""))),
                   Tbody(*ms_rows or [Tr(Td("No milestones.", colspan="5"))]), cls="tbl")

    rep_tbl = Table(
        Thead(Tr(Th("Period"), Th("Milestone"), Th("Claimed", cls="num"), Th("Disbursed", cls="num"), Th("Status"))),
        Tbody(*[Tr(Td(A(r["period"], href=f"/reports/{r['id']}")), Td(r["milestone"] or "—"),
                   Td(db.eur(r["amount_claimed"]), cls="num"), Td(db.eur(r["amount_disbursed"]), cls="num"),
                   Td(_pill(r["status"]))) for r in reps] or [Tr(Td("No reports yet.", colspan="5"))]), cls="tbl")

    pct = round(100 * disbursed / g["amount_awarded"]) if g["amount_awarded"] else 0
    info = Div(Div(H3("Agreement"), _pill(g["status"]), cls="card-header"),
               Div(Span("Reference", cls="k"), Span(g["agreement_ref"]),
                   Span("Beneficiary", cls="k"), Span(g["beneficiary"] or "—"),
                   Span("Project", cls="k"), Span(g["project"] or "—"),
                   Span("Call", cls="k"), Span(g["call_name"] or "—"),
                   Span("Awarded", cls="k"), Span(db.eur(g["amount_awarded"])),
                   Span("Disbursed", cls="k"), Span(f"{db.eur(disbursed)} ({pct}%)"),
                   Span("Period", cls="k"), Span(f"{_ago(g['start_date'])} → {_ago(g['end_date'])}"),
                   cls="kv"),
               _bar(pct, "gold"),
               Div(A("Beneficiary application", href=f"/applications/{g['application_id']}", cls="btn sm"),
                   style="margin-top:12px;"), cls="card")

    left = Div(Div(Div(H3(f"Milestones & disbursement ({len(ms)})"), cls="card-header"), ms_tbl, cls="card"),
               Div(Div(H3(f"Beneficiary reports ({len(reps)})"), cls="card-header"), rep_tbl, cls="card"))
    return Div(left, Div(info), cls="detail-grid")


def grant_detail(gid):
    g = db.grant(gid)
    if not g:
        return _title("Grant not found"), P("No such grant.")
    return (_title(g["agreement_ref"], f"{g['beneficiary']} · {g['project']}", A("← All grants", href="/grants", cls="btn")),
            Div(grant_main(gid), id="grant-main"))


# ---------- reports ---------------------------------------------------------

def reports_list(status="All"):
    seg = Div(*[A(s, href=f"/reports?status={s}", cls="" + ("active" if status == s else ""))
                for s in ["All", *db.REPORT_STATUSES]], cls="seg")
    reps = db.reports(status)
    tbl = Table(
        Thead(Tr(Th("Agreement"), Th("Beneficiary"), Th("Period"), Th("Milestone"),
                 Th("Claimed", cls="num"), Th("Disbursed", cls="num"), Th("Status"), Th("Submitted"))),
        Tbody(*[Tr(
            Td(A(r["agreement_ref"] or "—", href=f"/reports/{r['id']}")),
            Td(r["beneficiary"] or "—"), Td(A(r["period"] or "—", href=f"/reports/{r['id']}")),
            Td((r["milestone"] or "—")[:24]), Td(db.eur(r["amount_claimed"]), cls="num"),
            Td(db.eur(r["amount_disbursed"]), cls="num"), Td(_pill(r["status"])),
            Td(_ago(r["submitted_on"]), style="color:var(--text-mute);"),
        ) for r in reps] or [Tr(Td("No reports match.", colspan="8"))]), cls="tbl")
    return _title("Beneficiary Reports", f"{len(reps)} periodic reports"), seg, Div(tbl, cls="card")


def report_main(rid):
    r = db.report(rid)
    if not r:
        return Div(P("No such report."))
    actions = None
    if r["status"] in ("Submitted", "Draft"):
        actions = Div(
            Button("✔ Approve & disburse", cls="btn ok",
                   **{"hx-post": f"/reports/{rid}/approve", "hx-target": "#report-main", "hx-swap": "innerHTML"}),
            Button("✱ Request changes", cls="btn danger",
                   **{"hx-post": f"/reports/{rid}/reject", "hx-target": "#report-main", "hx-swap": "innerHTML"}),
            style="display:flex;gap:8px;margin-top:14px;")
    left = Div(Div(Div(H3("Progress narrative"), cls="card-header"),
                   P(r["progress_summary"] or "", style="color:var(--text-dim);line-height:1.6;"), cls="card"))
    info = Div(Div(H3("Report"), _pill(r["status"]), cls="card-header"),
               Div(Span("Agreement", cls="k"),
                   Span(A(r["agreement_ref"] or "—", href=f"/grants/{r['grant_id']}")),
                   Span("Beneficiary", cls="k"), Span(r["beneficiary"] or "—"),
                   Span("Period", cls="k"), Span(r["period"] or "—"),
                   Span("Milestone", cls="k"), Span(r["milestone"] or "—"),
                   Span("Amount claimed", cls="k"), Span(db.eur(r["amount_claimed"])),
                   Span("Disbursed", cls="k"), Span(db.eur(r["amount_disbursed"])),
                   Span("Submitted", cls="k"), Span(_ago(r["submitted_on"])),
                   cls="kv"),
               actions, cls="card")
    return Div(left, Div(info), cls="detail-grid")


def report_detail(rid):
    r = db.report(rid)
    if not r:
        return _title("Report not found"), P("No such report.")
    return (_title(f"{r['period']}", f"{r['agreement_ref']} · {r['beneficiary']}",
                   A("← All reports", href="/reports", cls="btn")),
            Div(report_main(rid), id="report-main"))
