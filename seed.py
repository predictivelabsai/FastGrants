"""Generate a fully synthetic FastGrants database (deterministic, no PII).

Builds a small but complete EU-funds programme: several funding calls, a pool
of applicant organisations, applications spread across the intake workflow, and
— for the approved ones — grant agreements with milestones, disbursements and
beneficiary reports. All data is invented; any resemblance to real programmes
or organisations is coincidental.
"""
from __future__ import annotations

import random
from datetime import timedelta

import db

RNG = random.Random(20260716)
NOW = db.NOW


def _d(days_from_now: int) -> str:
    return (NOW + timedelta(days=days_from_now)).strftime("%Y-%m-%d")


def _dt(days_ago: int) -> str:
    return (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")


CALLS = [
    # (name, programme, budget, opens_days_ago, closes_days_from_now, status, description)
    ("Digital Europe — SME Digitalisation 2026", "Digital Europe Programme", 4_500_000, 120, 45, "Open",
     "Grants for SMEs adopting AI, cloud and cybersecurity tooling across the single market."),
    ("Horizon — Green Transition Pilots", "Horizon Europe", 8_000_000, 200, -10, "Evaluation",
     "Pilot demonstrators for energy efficiency, circular economy and clean mobility."),
    ("Interreg — Cross-border Digital Public Services", "Interreg Europe", 3_200_000, 90, 90, "Open",
     "Joint digital public-service projects between neighbouring regions."),
    ("Erasmus+ — Digital Skills Academies", "Erasmus+", 2_100_000, 300, -60, "Closed",
     "Vocational academies delivering advanced digital skills to under-served regions."),
    ("Recovery & Resilience — Public Sector Modernisation", "RRF", 12_000_000, 60, 120, "Open",
     "Modernisation of legacy public-administration IT and e-government services."),
    ("Innovation Fund — Deep-tech Scale-up", "EIC Accelerator", 6_500_000, 30, 30, "Draft",
     "Blended finance for deep-tech scale-ups (draft — not yet published)."),
]

ORG_PREFIX = ["Nordic", "Baltic", "Helios", "Vertex", "Lumen", "Cobalt", "Meridian", "Aurora",
              "Delta", "Terra", "Quanta", "Orbis", "Silva", "Pallas", "Cyan", "Ferro"]
ORG_SUFFIX = ["Labs", "Digital", "Solutions", "Institute", "Foundation", "Systems", "Collective",
              "Research", "Technologies", "Group", "Cooperative", "Network"]
COUNTRIES = ["EE", "LT", "LV", "PL", "FI", "SE", "DE", "FR", "NL", "IE", "PT", "SI", "CZ", "RO"]
CONTACT_FIRST = ["Alex", "Sam", "Jordan", "Robin", "Casey", "Morgan", "Riley", "Jamie", "Noa", "Kai"]
CONTACT_LAST = ["Kask", "Vaitkus", "Berzins", "Kowalski", "Virtanen", "Lind", "Meyer", "Dubois",
                "Visser", "Byrne", "Costa", "Novak"]

PROJECT_TITLES = [
    "AI-assisted grant compliance for municipalities",
    "Federated data platform for regional SMEs",
    "Low-carbon logistics optimisation pilot",
    "Open-source e-government identity wallet",
    "Circular-economy marketplace for manufacturers",
    "Digital-skills bootcamp for rural workforce",
    "Predictive maintenance for district heating",
    "Cross-border e-invoicing interoperability",
    "Green hydrogen feasibility demonstrator",
    "Accessibility-first public-service portal",
    "Smart-grid demand response toolkit",
    "Multilingual citizen-services chatbot",
    "Cyber-resilience uplift for water utilities",
    "Farm-to-fork traceability blockchain pilot",
    "Inclusive fintech for the unbanked",
    "Coastal flood early-warning network",
]
SUMMARIES = [
    "The project delivers a reusable, open-source component addressing a concrete gap identified in the call, "
    "with pilots in at least two member states and a clear exploitation plan.",
    "A 24-month action combining applied research, a working demonstrator and a dissemination programme "
    "targeting public-sector adopters.",
    "The consortium proposes a staged rollout: requirements, prototype, field pilot and evaluation against "
    "measurable KPIs aligned to the programme objectives.",
]
PERIODS = ["Period 1 (M1–M6)", "Period 2 (M7–M12)", "Period 3 (M13–M18)"]
PROGRESS = [
    "All planned activities on track; kick-off completed, project management structures in place.",
    "Prototype delivered and first pilot launched; minor delay on procurement mitigated.",
    "Interim results validated with stakeholders; dissemination reaching target audience.",
]


def build():
    db.init_schema()
    with db.cursor() as conn:
        for t in ("chat_messages", "activity", "reports", "milestones", "grants",
                  "documents", "applications", "applicants", "calls"):
            conn.execute(f"DELETE FROM {t}")

    # --- calls --------------------------------------------------------------
    with db.cursor() as conn:
        for name, prog, budget, opened, closes, status, desc in CALLS:
            conn.execute(
                """INSERT INTO calls(name,programme,description,budget_total,currency,opens_on,closes_on,status,created)
                   VALUES (?,?,?,?, 'EUR', ?,?,?,?)""",
                (name, prog, desc, budget, _d(-opened), _d(closes), status, _dt(opened)))
        call_rows = conn.execute("SELECT id,name,status,budget_total FROM calls").fetchall()
    calls = [dict(r) for r in call_rows]
    live_calls = [c for c in calls if c["status"] != "Draft"]

    # --- applicants ---------------------------------------------------------
    applicants = []
    used = set()
    while len(applicants) < 24:
        nm = f"{RNG.choice(ORG_PREFIX)} {RNG.choice(ORG_SUFFIX)}"
        if nm in used:
            continue
        used.add(nm)
        fn, ln = RNG.choice(CONTACT_FIRST), RNG.choice(CONTACT_LAST)
        slug = nm.lower().replace(" ", "")
        applicants.append((nm, RNG.choice(db.ORG_TYPES), RNG.choice(COUNTRIES),
                           f"{fn} {ln}", f"{fn.lower()}.{ln.lower()}@{slug}.example",
                           _dt(RNG.randint(120, 600))))
    with db.cursor() as conn:
        conn.executemany(
            "INSERT INTO applicants(name,org_type,country,contact_name,contact_email,created) VALUES (?,?,?,?,?,?)",
            applicants)
        applicant_ids = [r[0] for r in conn.execute("SELECT id FROM applicants").fetchall()]

    # --- applications -------------------------------------------------------
    # Weighted status mix that yields a realistic pipeline + a batch of awards.
    status_pool = (["Submitted"] * 8 + ["Under Review"] * 6 + ["Approved"] * 10
                   + ["Rejected"] * 5 + ["Draft"] * 3)
    apps = []
    n_app = 34
    for i in range(n_app):
        call = RNG.choice(live_calls)
        applicant = RNG.choice(applicant_ids)
        title = RNG.choice(PROJECT_TITLES)
        status = RNG.choice(status_pool)
        # request between 5% and 20% of the call budget, capped for realism
        amount = round(RNG.uniform(0.03, 0.16) * call["budget_total"] / 1000) * 1000
        amount = min(amount, 900_000)
        submitted = None if status == "Draft" else _dt(RNG.randint(15, 180))
        decided = _dt(RNG.randint(5, 40)) if status in ("Approved", "Rejected") else None
        score = round(RNG.uniform(3.0, 9.8), 1) if status != "Draft" else None
        ref = f"APP-{NOW.year}-{i + 1001}"
        apps.append((ref, call["id"], applicant, title,
                     RNG.choice(SUMMARIES), amount, status, score, submitted, decided,
                     submitted or _dt(RNG.randint(180, 240))))
    with db.cursor() as conn:
        conn.executemany(
            """INSERT INTO applications
               (ref,call_id,applicant_id,title,summary,amount_requested,status,score,submitted_on,decided_on,created)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""", apps)
        app_rows = [dict(r) for r in conn.execute(
            "SELECT id,status,amount_requested,submitted_on FROM applications").fetchall()]

    # --- documents ----------------------------------------------------------
    docs = []
    for a in app_rows:
        for dtp in RNG.sample(db.DOC_TYPES, RNG.randint(4, 6)):
            st = "Missing" if RNG.random() < 0.12 else RNG.choice(["Received", "Verified", "Verified"])
            docs.append((a["id"], f"{dtp}.pdf", dtp, st))
    with db.cursor() as conn:
        conn.executemany("INSERT INTO documents(application_id,name,doc_type,status) VALUES (?,?,?,?)", docs)

    # --- grants + milestones + reports (for approved applications) ----------
    grants, milestones, reports, acts = [], [], [], []
    for a in [x for x in app_rows if x["status"] == "Approved"]:
        aid = a["id"]
        amount = a["amount_requested"] or 0
        gstatus = RNG.choices(["Active", "Completed"], weights=[75, 25])[0]
        start_days_ago = RNG.randint(60, 400)
        ref = f"GA-{NOW.year}-{aid:04d}"
        grants.append((ref, aid, amount, "EUR", _d(-start_days_ago), _d(730 - start_days_ago),
                       gstatus, _dt(start_days_ago)))
    with db.cursor() as conn:
        conn.executemany(
            """INSERT INTO grants(agreement_ref,application_id,amount_awarded,currency,start_date,end_date,status,created)
               VALUES (?,?,?,?,?,?,?,?)""", grants)
        grant_rows = [dict(r) for r in conn.execute(
            "SELECT id,amount_awarded,status,start_date,created FROM grants").fetchall()]

    tranche_spec = [("Pre-financing (kick-off)", 0.4, 30),
                    ("Interim report & payment", 0.4, 365),
                    ("Final report & balance", 0.2, 700)]
    for g in grant_rows:
        gid = g["id"]
        start = db._parse(g["start_date"]) or NOW
        completed = g["status"] == "Completed"
        for idx, (title, frac, offset) in enumerate(tranche_spec):
            due = (start + timedelta(days=offset)).strftime("%Y-%m-%d")
            amt = round(g["amount_awarded"] * frac)
            # earlier tranches likelier disbursed; completed grants fully paid
            if completed:
                disbursed = 1
            else:
                disbursed = 1 if (idx == 0 or (idx == 1 and RNG.random() < 0.5)) else 0
            if disbursed:
                status = "Completed"
            elif db._parse(due) and db._parse(due) < NOW:
                status = "Overdue"
            elif idx == 1:
                status = "In Progress"
            else:
                status = "Pending"
            disb_on = _dt(RNG.randint(5, 200)) if disbursed else None
            milestones.append((gid, title, due, amt, status, disbursed, disb_on))
    with db.cursor() as conn:
        conn.executemany(
            "INSERT INTO milestones(grant_id,title,due_date,amount,status,disbursed,disbursed_on) VALUES (?,?,?,?,?,?,?)",
            milestones)
        ms_rows = [dict(r) for r in conn.execute(
            "SELECT id,grant_id,title,amount,disbursed FROM milestones ORDER BY grant_id,id").fetchall()]

    ms_by_grant = {}
    for m in ms_rows:
        ms_by_grant.setdefault(m["grant_id"], []).append(m)

    for g in grant_rows:
        gid = g["id"]
        gms = ms_by_grant.get(gid, [])
        n_reports = sum(1 for m in gms if m["disbursed"]) + (1 if g["status"] == "Active" else 0)
        for p in range(min(n_reports, len(PERIODS))):
            ms = gms[p] if p < len(gms) else None
            approved = ms and ms["disbursed"]
            claimed = ms["amount"] if ms else round(g["amount_awarded"] * 0.3)
            rstatus = "Approved" if approved else RNG.choice(["Submitted", "Submitted", "Draft"])
            disb = claimed if rstatus == "Approved" else 0
            reports.append((gid, ms["id"] if ms else None, PERIODS[p], RNG.choice(PROGRESS),
                            claimed, disb, rstatus, _dt(RNG.randint(10, 150)), _dt(RNG.randint(10, 160))))
        acts.append(("grant", gid, "Grant agreement signed", "Programme Officer", g["created"]))
    with db.cursor() as conn:
        conn.executemany(
            """INSERT INTO reports(grant_id,milestone_id,period,progress_summary,amount_claimed,amount_disbursed,
                                   status,submitted_on,created) VALUES (?,?,?,?,?,?,?,?,?)""", reports)
        conn.executemany(
            "INSERT INTO activity(entity_type,entity_id,action,actor,created) VALUES (?,?,?,?,?)", acts)

    print(f"FastGrants seeded → {db.DB_PATH}")
    print(f"  {len(live_calls)} live calls (+1 draft) · {len(applicants)} applicants · {len(apps)} applications")
    print(f"  {len(grants)} grant agreements · {len(milestones)} milestones · {len(reports)} reports")
    k = db.kpis()
    print(f"  budget {db.eur(k['total_budget'])} · allocated {db.eur(k['allocated'])} · disbursed {db.eur(k['disbursed'])}")


if __name__ == "__main__":
    build()
