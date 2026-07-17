"""FastGrants AI assistant — slash-commands + grounded multi-provider chat.

Slash-commands resolve locally against SQLite (no API key). Free-form chat is
streamed from a configurable provider, grounded with a live snapshot of the
programme so answers reflect the actual calls, applications and disbursement.
Two flagship uses: eligibility Q&A over call rules and application summarisation.
"""
from __future__ import annotations

import json
import os

import db

PROVIDER = os.getenv("MODEL_PROVIDER", "xai")
MODEL = os.getenv("MODEL_NAME", "grok-4-1-fast-reasoning")


def snapshot() -> str:
    k = db.kpis()
    by_status = db.apps_by_status()
    lines = [
        "CURRENT PROGRAMME SNAPSHOT (synthetic demo data):",
        f"- Programme budget: {db.eur(k['total_budget'])}. Allocated (awarded): {db.eur(k['allocated'])} "
        f"({k['committed_pct']}% committed). Disbursed: {db.eur(k['disbursed'])} ({k['disbursed_pct']}% of allocated).",
        f"- Active grants: {k['active_grants']}. Open applications: {k['open_apps']}. Approval rate: {k['approval_rate']}%.",
        "Applications by status: " + ", ".join(f"{s} {by_status.get(s, 0)}" for s in db.APP_STATUSES),
    ]
    calls = db.calls()
    if calls:
        lines.append("Open calls: " + "; ".join(
            f"{c['name']} ({db.eur(c['budget_total'])}, closes {(c['closes_on'] or '')[:10]}, {c['app_n']} apps)"
            for c in calls if c["status"] == "Open"))
    overdue = db.rows(
        "SELECT COUNT(*) n FROM milestones WHERE disbursed=0 AND due_date < ?",
        (db.NOW.strftime("%Y-%m-%d"),))
    lines.append(f"Overdue (undisbursed) milestones: {overdue[0]['n'] if overdue else 0}.")
    return "\n".join(lines)


SYSTEM_PROMPT = """You are the FastGrants assistant, embedded in an open-source grant / EU-funds
lifecycle platform used by a funding body to ADMINISTER grants (intake, award, disburse, monitor) —
you do not evaluate or score proposals on scientific merit. Help programme officers answer eligibility
questions against call rules, summarise applications, track budget and disbursement, and spot overdue
milestones or reports. Be concise and practical; use Markdown (short tables, bold figures) when it helps.
All data is synthetic demo data — never claim it is real. Base answers on the PROGRAMME SNAPSHOT below;
if something isn't in it, say so plainly rather than inventing."""


def _table(headers, rows_):
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for r in rows_:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def handle_command(text: str):
    if not text.startswith("/"):
        return None
    parts = text[1:].split()
    cmd = parts[0].lower() if parts else ""
    arg = " ".join(parts[1:])

    if cmd in ("help", "?"):
        return ("**FastGrants shortcuts**\n\n"
                "- `/budget` — allocated vs disbursed by call\n"
                "- `/pipeline` — applications by workflow stage\n"
                "- `/calls` — open funding calls\n"
                "- `/review` — applications awaiting a decision\n"
                "- `/grants` — active grant agreements\n"
                "- `/overdue` — undisbursed milestones past due\n"
                "- `/kpi` — headline numbers\n\nOr ask a question in plain English.")

    if cmd == "kpi":
        k = db.kpis()
        return _table(["Metric", "Value"], [
            ["Programme budget", db.eur(k["total_budget"])],
            ["Allocated", db.eur(k["allocated"])],
            ["Disbursed", db.eur(k["disbursed"])],
            ["Committed %", f"{k['committed_pct']}%"],
            ["Open applications", k["open_apps"]],
            ["Active grants", k["active_grants"]],
            ["Approval rate", f"{k['approval_rate']}%"]])

    if cmd == "budget":
        rows_ = db.budget_by_call()
        if not rows_:
            return "No calls yet."
        return "**Budget by call**\n\n" + _table(
            ["Call", "Budget", "Allocated", "Disbursed"],
            [[c["name"][:26], db.eur(c["budget_total"]), db.eur(c["allocated"]), db.eur(c["disbursed"])] for c in rows_])

    if cmd == "pipeline":
        by = db.apps_by_status()
        return "**Application pipeline**\n\n" + _table(
            ["Stage", "Applications"], [[s, by.get(s, 0)] for s in db.APP_STATUSES])

    if cmd == "calls":
        rows_ = [c for c in db.calls() if c["status"] in ("Open", "Evaluation")]
        if not rows_:
            return "No open calls."
        return "**Open calls**\n\n" + _table(
            ["Call", "Budget", "Closes", "Apps"],
            [[c["name"][:28], db.eur(c["budget_total"]), (c["closes_on"] or "")[:10], c["app_n"]] for c in rows_])

    if cmd == "review":
        rows_ = db.applications("Open")
        if not rows_:
            return "No applications awaiting review. 🎉"
        return "**Awaiting decision**\n\n" + _table(
            ["Ref", "Project", "Applicant", "Requested", "Status"],
            [[a["ref"], a["title"][:28], a["applicant"], db.eur(a["amount_requested"]), a["status"]] for a in rows_[:15]])

    if cmd == "grants":
        rows_ = db.grants("Active")
        if not rows_:
            return "No active grants."
        return "**Active grants**\n\n" + _table(
            ["Agreement", "Beneficiary", "Awarded", "Disbursed"],
            [[g["agreement_ref"], g["beneficiary"], db.eur(g["amount_awarded"]), db.eur(g["disbursed"])] for g in rows_[:15]])

    if cmd == "overdue":
        rows_ = db.rows(
            """SELECT m.title, m.amount, m.due_date, g.agreement_ref, ap.name beneficiary
               FROM milestones m JOIN grants g ON g.id=m.grant_id
               LEFT JOIN applications a ON a.id=g.application_id
               LEFT JOIN applicants ap ON ap.id=a.applicant_id
               WHERE m.disbursed=0 AND m.due_date < ? ORDER BY m.due_date LIMIT 15""",
            (db.NOW.strftime("%Y-%m-%d"),))
        if not rows_:
            return "No overdue milestones. 🎉"
        return "**Overdue milestones**\n\n" + _table(
            ["Agreement", "Beneficiary", "Milestone", "Amount", "Due"],
            [[r["agreement_ref"], r["beneficiary"], r["title"][:24], db.eur(r["amount"]), (r["due_date"] or "")[:10]]
             for r in rows_])

    return f"Unknown command `/{cmd}`. Try `/help`."


async def stream_chat(message: str):
    cmd = handle_command(message)
    if cmd is not None:
        yield f"data: {json.dumps({'token': cmd})}\n\n"
        yield f"data: {json.dumps({'done': True})}\n\n"
        return
    system = SYSTEM_PROMPT + "\n\n" + snapshot()
    try:
        async for tok in _provider_stream(system, message):
            yield f"data: {json.dumps({'token': tok})}\n\n"
    except Exception as e:  # noqa: BLE001
        yield f"data: {json.dumps({'error': str(e)})}\n\n"
    yield f"data: {json.dumps({'done': True})}\n\n"


async def _provider_stream(system, message):
    import httpx
    provider, model = PROVIDER, MODEL
    if provider in ("xai", "openai"):
        url = "https://api.x.ai/v1/chat/completions" if provider == "xai" else "https://api.openai.com/v1/chat/completions"
        key = os.getenv("XAI_API_KEY" if provider == "xai" else "OPENAI_API_KEY", "")
        if not key:
            yield _no_key(provider); return
        async with httpx.AsyncClient(timeout=90) as client:
            async with client.stream("POST", url, headers={"Authorization": f"Bearer {key}"},
                                     json={"model": model, "stream": True,
                                           "messages": [{"role": "system", "content": system},
                                                        {"role": "user", "content": message}]}) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data: ") and line != "data: [DONE]":
                        try:
                            tok = json.loads(line[6:])["choices"][0]["delta"].get("content", "")
                            if tok: yield tok
                        except (json.JSONDecodeError, KeyError, IndexError):
                            pass
    elif provider == "anthropic":
        key = os.getenv("ANTHROPIC_API_KEY", "")
        if not key:
            yield _no_key(provider); return
        async with httpx.AsyncClient(timeout=90) as client:
            async with client.stream("POST", "https://api.anthropic.com/v1/messages",
                                     headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                                     json={"model": model, "max_tokens": 1500, "stream": True,
                                           "system": system, "messages": [{"role": "user", "content": message}]}) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        try:
                            ev = json.loads(line[6:])
                            if ev.get("type") == "content_block_delta":
                                tok = ev.get("delta", {}).get("text", "")
                                if tok: yield tok
                        except json.JSONDecodeError:
                            pass
    elif provider == "google":
        key = os.getenv("GOOGLE_API_KEY", "")
        if not key:
            yield _no_key(provider); return
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse&key={key}"
        async with httpx.AsyncClient(timeout=90) as client:
            async with client.stream("POST", url, json={
                "system_instruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": message}]}]}) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        try:
                            tok = json.loads(line[6:])["candidates"][0]["content"]["parts"][0].get("text", "")
                            if tok: yield tok
                        except (json.JSONDecodeError, KeyError, IndexError):
                            pass
    else:
        yield (f"No LLM provider configured (MODEL_PROVIDER='{provider}'). Set it to xai/openai/anthropic/google "
               "in `.env`. Slash-commands like `/budget` work without a key.")


def _no_key(provider):
    env = {"xai": "XAI_API_KEY", "openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "google": "GOOGLE_API_KEY"}[provider]
    return (f"⚠ No **{env}** set, so free-form chat is disabled. Add it to `.env` and restart. "
            "Slash-commands (`/budget`, `/pipeline`, `/review` …) work without any key.")
