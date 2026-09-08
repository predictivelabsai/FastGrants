from web.landing import landing_page
"""FastGrants — an open-source grant / EU-funds lifecycle platform built with FastHTML.

A server-side, HTMX-driven platform for administering public grants end to end:
funding calls, application intake with a submitted → under review → approved/rejected
workflow, grant agreements with milestone-tranche disbursement, beneficiary reporting,
Plotly dashboards, and an AI assistant grounded in the live (synthetic) programme.

Run:
    python web_app.py            # http://localhost:5015

Login: admin@fastgrants.example / FastGrants2026$  (override via .env)
"""
from __future__ import annotations

import os
import json
import secrets
import uuid
import logging

from dotenv import load_dotenv
load_dotenv()

from fasthtml.common import (
    fast_app, serve, Div, H1, P, A, Form, Input, Button, NotStr,
    RedirectResponse, Script, Style, Link, Title,
)
from starlette.responses import StreamingResponse, Response

import db
from web.layout import page, LAYOUT_CSS
from web import views, ai

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger("fastgrants")

VALID_EMAIL = os.getenv("FASTGRANTS_ADMIN_EMAIL", "admin@fastgrants.example")
VALID_PASSWORD = os.getenv("FASTGRANTS_ADMIN_PASSWORD", "FastGrants2026$")
ENV_LABEL = os.getenv("FASTGRANTS_ENV_LABEL", "FastGrants")
SECRET = os.getenv("FASTGRANTS_SECRET", secrets.token_hex(32))
PORT = int(os.getenv("FASTGRANTS_PORT", "5015"))

app, rt = fast_app(live=False, pico=False, secret_key=SECRET, hdrs=[Style(LAYOUT_CSS)])


def _user(session):
    return session.get("user")


def _thread(session):
    if "thread" not in session:
        session["thread"] = uuid.uuid4().hex
    return session["thread"]


def _guard(session, active, builder):
    if not _user(session):
        return RedirectResponse("/login", status_code=303)
    content = builder() if callable(builder) else builder
    if not isinstance(content, tuple):
        content = (content,)
    return page(active, ENV_LABEL, _user(session), _thread(session), *content)


def _frag(session, fn, *a):
    if not _user(session):
        return Response("Unauthorized", status_code=401)
    return fn(*a)


def _login_card(error="", email=""):
    return Title("FastGrants — Sign in"), Style(LAYOUT_CSS), Div(
        Form(H1("FastGrants"), P("Sign in to your grant management workspace"),
             Input(name="email", type="email", placeholder="Email", value=email, required=True),
             Input(name="password", type="password", placeholder="Password", required=True),
             P(error, cls="error") if error else None,
             Button("Sign in", cls="btn primary", type="submit"),
             P(NotStr("Demo: <code>admin@fastgrants.example</code> / <code>FastGrants2026$</code>"), cls="hint"),
             method="post", action="/login", cls="login-card"), cls="login-wrap")


@rt("/login")
def get(session):
    if _user(session):
        return RedirectResponse("/", status_code=303)
    return _login_card()


@rt("/login")
def post(session, email: str = "", password: str = ""):
    if email.strip().lower() == VALID_EMAIL.lower() and password == VALID_PASSWORD:
        session["user"] = email.strip().lower()
        return RedirectResponse("/", status_code=303)
    return _login_card("Invalid email or password.", email)


@rt("/logout")
def get(session):
    session.pop("user", None)
    return RedirectResponse("/login", status_code=303)


# --- dashboard --------------------------------------------------------------

@rt("/")
def get(session):
    if not _user(session):
        return landing_page()
    return _guard(session, "dashboard", views.dashboard)



# --- calls ------------------------------------------------------------------

@rt("/calls")
def get(session):
    return _guard(session, "calls", views.calls_list)


@rt("/calls/{cid}")
def get(session, cid: int):
    return _guard(session, "calls", lambda: views.call_detail(cid))


# --- applications -----------------------------------------------------------

@rt("/applications")
def get(session, status: str = "All"):
    return _guard(session, "applications", lambda: views.applications_list(status))


@rt("/applications/{aid}")
def get(session, aid: int):
    return _guard(session, "applications", lambda: views.application_detail(aid))


@rt("/applications/{aid}/{action}")
def post(session, aid: int, action: str):
    if not _user(session):
        return Response("Unauthorized", status_code=401)
    db.advance_application(aid, action)
    return views.application_main(aid)


# --- grants -----------------------------------------------------------------

@rt("/grants")
def get(session, status: str = "All"):
    return _guard(session, "grants", lambda: views.grants_list(status))


@rt("/grants/{gid}")
def get(session, gid: int):
    return _guard(session, "grants", lambda: views.grant_detail(gid))


@rt("/grants/{gid}/milestones/{mid}/disburse")
def post(session, gid: int, mid: int):
    if not _user(session):
        return Response("Unauthorized", status_code=401)
    db.disburse_milestone(mid)
    return views.grant_main(gid)


# --- reports ----------------------------------------------------------------

@rt("/reports")
def get(session, status: str = "All"):
    return _guard(session, "reports", lambda: views.reports_list(status))


@rt("/reports/{rid}")
def get(session, rid: int):
    return _guard(session, "reports", lambda: views.report_detail(rid))


@rt("/reports/{rid}/{action}")
def post(session, rid: int, action: str):
    if not _user(session):
        return Response("Unauthorized", status_code=401)
    db.review_report(rid, action)
    return views.report_main(rid)


# --- AI + guide -------------------------------------------------------------

@rt("/ai")
def get(session):
    body = (views._title("AI Assistant", "Chat lives in the right rail. Ask in plain English or use slash-commands."),
            Div(NotStr(
                "<div class='card'><h3>What you can ask</h3><ul style='line-height:1.8;'>"
                "<li>“Is a large enterprise eligible for the SME Digitalisation call?”</li>"
                "<li>“Summarise the applications awaiting review.”</li>"
                "<li>“How much budget is still uncommitted?”</li>"
                "<li>“Which grants have overdue milestones?”</li></ul>"
                "<p style='color:var(--text-mute)'>Slash-commands resolve instantly with no API key: "
                "<code>/budget</code> <code>/pipeline</code> <code>/calls</code> <code>/review</code> "
                "<code>/grants</code> <code>/overdue</code> <code>/kpi</code> <code>/help</code></p></div>")))
    return _guard(session, "ai", body)


@rt("/guide")
def get(session):
    body = (views._title("User Guide", "How to drive FastGrants"), Div(NotStr("""
<div class='card'><h3>Dashboard</h3><p>Programme KPIs (budget, allocated, disbursed, open applications),
a Plotly view of budget allocated-vs-disbursed by call, a disbursement-rate gauge, the application
pipeline, and an "overdue milestones" worklist.</p></div>
<div class='card'><h3>Calls &amp; Programmes</h3><p>Every funding call with its budget, open/close dates,
status and application count. Open a call to see all of its applications.</p></div>
<div class='card'><h3>Applications</h3><p>The intake queue. Filter by status and open any application for
the project summary, supporting documents and the decision workflow:
<em>Submitted → Under Review → Approved / Rejected</em>. Approving an application automatically creates a
grant agreement with three disbursement tranches.</p></div>
<div class='card'><h3>Grants &amp; Agreements</h3><p>Awarded grants with milestone tranches. Disburse a
milestone to record a payment; progress bars track disbursed-vs-awarded.</p></div>
<div class='card'><h3>Beneficiary Reports</h3><p>Periodic progress + financial reports. Approving a report
disburses its linked milestone tranche and marks it paid.</p></div>
<div class='card'><h3>AI Assistant</h3><p>The right rail chats over a live snapshot of the programme — eligibility
Q&amp;A and application summarisation. Set <code>MODEL_PROVIDER</code> + an API key in <code>.env</code> for
free-form chat; slash-commands always work.</p></div>
""")))
    return _guard(session, "guide", body)


# --- AI chat (SSE) ----------------------------------------------------------

@rt("/chat/new")
def get(session):
    session["thread"] = uuid.uuid4().hex
    return P("Ask about calls, applications, disbursement or eligibility — or tap a question below.",
             cls="chat-empty-hint")


@rt("/chat/stream")
async def post(session, message: str = "", thread_id: str = ""):
    if not _user(session):
        return Response("Unauthorized", status_code=401)
    message = (message or "").strip()
    if not message:
        return Response("No message", status_code=400)
    tid = thread_id or _thread(session)

    async def gen():
        with db.cursor() as conn:
            conn.execute("INSERT INTO chat_messages(thread_id,role,content,created) VALUES(?,?,?,datetime('now'))",
                         (tid, "user", message))
        full = []
        async for chunk in ai.stream_chat(message):
            if chunk.startswith("data: "):
                try:
                    tok = json.loads(chunk[6:]).get("token")
                    if tok:
                        full.append(tok)
                except Exception:
                    pass
            yield chunk
        with db.cursor() as conn:
            conn.execute("INSERT INTO chat_messages(thread_id,role,content,created) VALUES(?,?,?,datetime('now'))",
                         (tid, "assistant", "".join(full)))

    return StreamingResponse(gen(), media_type="text/event-stream")


def _ensure_db():
    if not db.db_exists():
        logger.info("No database found — seeding synthetic data…")
        import seed
        seed.build()
    else:
        db.init_schema()  # idempotent


_ensure_db()

if __name__ == "__main__":
    logger.info("FastGrants on http://localhost:%s  (login %s)", PORT, VALID_EMAIL)
    serve(port=PORT, reload=os.getenv("FASTGRANTS_RELOAD", "0") == "1")
