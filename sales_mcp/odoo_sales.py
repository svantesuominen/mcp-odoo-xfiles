"""Odoo XML-RPC helpers for Sales MCP: users, partners, activities."""

import html
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from odoo_connection import ODOO_DB, ODOO_PASSWORD, ODOO_URL, get_odoo_connection

# Default activity type names (override via env)
_CALL_TYPE_NAME = os.getenv("ODOO_CALL_ACTIVITY_TYPE_NAME") or "Call"
_MEETING_TYPE_NAME = os.getenv("ODOO_MEETING_ACTIVITY_TYPE_NAME") or "Meeting"

_TZ = ZoneInfo(os.getenv("ODOO_SALES_DATE_TZ") or "Europe/Helsinki")

_activity_type_cache: Dict[str, int] = {}
_ir_model_id_cache: Dict[str, int] = {}


def today_yyyy_mm_dd() -> str:
    return datetime.now(_TZ).date().isoformat()


def resolve_salesperson_user_id(salesperson_email: str) -> int:
    email = (salesperson_email or "").strip().lower()
    if not email:
        raise ValueError("salesperson_email is required.")
    uid, models = get_odoo_connection()
    found = models.execute_kw(
        ODOO_DB,
        uid,
        ODOO_PASSWORD,
        "res.users",
        "search_read",
        [[("login", "ilike", email), ("active", "=", True)]],
        {"fields": ["id"], "limit": 2},
    )
    if not found:
        raise ValueError(f"No active Odoo user found for login/email: {salesperson_email!r}")
    if len(found) > 1:
        raise ValueError(f"Multiple Odoo users match email: {salesperson_email!r}")
    return found[0]["id"]


def ir_model_id_for(model_name: str) -> int:
    if model_name in _ir_model_id_cache:
        return _ir_model_id_cache[model_name]
    uid, models = get_odoo_connection()
    mids = models.execute_kw(
        ODOO_DB,
        uid,
        ODOO_PASSWORD,
        "ir.model",
        "search",
        [[("model", "=", model_name)]],
        {"limit": 1},
    )
    if not mids:
        raise ValueError(f"ir.model not found for {model_name!r}")
    _ir_model_id_cache[model_name] = mids[0]
    return mids[0]


def activity_type_id_for(interaction_type: str) -> int:
    name = _CALL_TYPE_NAME if interaction_type == "call" else _MEETING_TYPE_NAME
    if name in _activity_type_cache:
        return _activity_type_cache[name]
    uid, models = get_odoo_connection()
    rows = models.execute_kw(
        ODOO_DB,
        uid,
        ODOO_PASSWORD,
        "mail.activity.type",
        "search_read",
        [[("name", "=ilike", name)]],
        {"fields": ["id", "name"], "limit": 5},
    )
    if not rows:
        raise ValueError(
            f'No mail.activity.type found with name ilike {name!r}. '
            f"Set ODOO_CALL_ACTIVITY_TYPE_NAME or ODOO_MEETING_ACTIVITY_TYPE_NAME."
        )
    tid = rows[0]["id"]
    _activity_type_cache[name] = tid
    return tid


def partner_form_url(partner_id: int) -> str:
    base = ODOO_URL.rstrip("/")
    return f"{base}/web#id={partner_id}&model=res.partner&view_type=form"


def lead_form_url(lead_id: int) -> str:
    base = ODOO_URL.rstrip("/")
    return f"{base}/web#id={lead_id}&model=crm.lead&view_type=form"


def search_partners_company_normalized(query: str, limit: int = 20) -> List[Dict[str, Any]]:
    """
    Search res.partner; normalize each hit to commercial_partner_id (company).
    Dedupe by company id.
    """
    q = (query or "").strip()
    if not q:
        return []
    uid, models = get_odoo_connection()
    # OR across name, email, phone, mobile (all ilike query string)
    domain: List[Any] = [
        "|",
        "|",
        "|",
        ("name", "ilike", q),
        ("email", "ilike", q),
        ("phone", "ilike", q),
        ("mobile", "ilike", q),
    ]
    partner_ids = models.execute_kw(
        ODOO_DB,
        uid,
        ODOO_PASSWORD,
        "res.partner",
        "search",
        [domain],
        {"limit": limit, "order": "name"},
    )
    if not partner_ids:
        return []
    fields = [
        "id",
        "name",
        "is_company",
        "commercial_partner_id",
        "email",
        "phone",
        "mobile",
    ]
    rows = models.execute_kw(
        ODOO_DB,
        uid,
        ODOO_PASSWORD,
        "res.partner",
        "read",
        [partner_ids],
        {"fields": fields},
    )
    seen: set = set()
    out: List[Dict[str, Any]] = []
    for r in rows:
        cp = r.get("commercial_partner_id")
        company_id = cp[0] if cp else r["id"]
        if company_id in seen:
            continue
        seen.add(company_id)
        if company_id != r["id"]:
            companies = models.execute_kw(
                ODOO_DB,
                uid,
                ODOO_PASSWORD,
                "res.partner",
                "read",
                [[company_id]],
                {"fields": ["id", "name", "email", "phone", "mobile"]},
            )
            if not companies:
                continue
            c = companies[0]
        else:
            c = r
        out.append(
            {
                "partner_id": company_id,
                "name": c.get("name") or "",
                "email": c.get("email") or "",
                "phone": c.get("phone") or c.get("mobile") or "",
                "url": partner_form_url(company_id),
                "matched_contact_name": r.get("name") if company_id != r["id"] else None,
            }
        )
    return out


def search_leads(query: str, limit: int = 15) -> List[Dict[str, Any]]:
    q = (query or "").strip()
    if not q:
        return []
    uid, models = get_odoo_connection()
    domain = ["|", ("name", "ilike", q), ("partner_name", "ilike", q)]
    lead_ids = models.execute_kw(
        ODOO_DB,
        uid,
        ODOO_PASSWORD,
        "crm.lead",
        "search",
        [domain],
        {"limit": limit, "order": "write_date desc"},
    )
    if not lead_ids:
        return []
    rows = models.execute_kw(
        ODOO_DB,
        uid,
        ODOO_PASSWORD,
        "crm.lead",
        "read",
        [lead_ids],
        {"fields": ["id", "name", "partner_id", "stage_id", "email_from"]},
    )
    out = []
    for r in rows:
        out.append(
            {
                "opportunity_id": r["id"],
                "name": r.get("name") or "",
                "partner_id": r["partner_id"][0] if r.get("partner_id") else None,
                "partner_name": r["partner_id"][1] if r.get("partner_id") else None,
                "stage_id": r["stage_id"][1] if r.get("stage_id") else None,
                "email_from": r.get("email_from") or "",
                "url": lead_form_url(r["id"]),
            }
        )
    return out


_DISCLAIMER_START = re.compile(
    r"(?ms)^\s*(Tiivistelmä luotu|Summary created).*$",
    re.IGNORECASE,
)


def strip_trailing_disclaimer(body: str) -> str:
    """Remove common AI summary disclaimer block at end of paste."""
    cut = _DISCLAIMER_START.search(body)
    if cut:
        body = body[: cut.start()].rstrip()
    return body


def _body_to_html_feedback(body: str) -> str:
    safe = html.escape(body.strip())
    parts = safe.split("\n\n")
    paras = "".join(f"<p>{p.replace(chr(10), '<br/>')}</p>" for p in parts if p.strip())
    return paras or "<p></p>"


def log_activity_on_record(
    res_model: str,
    res_id: int,
    interaction_type: str,
    salesperson_user_id: int,
    note_body: str,
    occurred_on: Optional[str],
) -> Dict[str, Any]:
    """
    Create a mail.activity and immediately complete it via action_feedback
    so chatter shows a done Call/Meeting with notes.
    """
    uid, models = get_odoo_connection()
    type_id = activity_type_id_for(interaction_type)
    res_model_id = ir_model_id_for(res_model)
    deadline = occurred_on or today_yyyy_mm_dd()
    summary = "Call" if interaction_type == "call" else "Meeting"
    act_vals = {
        "res_model": res_model,
        "res_model_id": res_model_id,
        "res_id": res_id,
        "activity_type_id": type_id,
        "user_id": salesperson_user_id,
        "summary": summary,
        "date_deadline": deadline,
    }
    act_id = models.execute_kw(
        ODOO_DB,
        uid,
        ODOO_PASSWORD,
        "mail.activity",
        "create",
        [act_vals],
    )
    feedback_html = _body_to_html_feedback(note_body)
    models.execute_kw(
        ODOO_DB,
        uid,
        ODOO_PASSWORD,
        "mail.activity",
        "action_feedback",
        [[act_id]],
        {"feedback": feedback_html},
    )
    return {"activity_id": act_id, "res_model": res_model, "res_id": res_id}
