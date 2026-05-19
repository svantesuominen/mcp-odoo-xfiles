"""Aggregate Odoo data for a single client (commercial partner) dossier."""

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from html_util import html_to_plain_text
from odoo_connection import ODOO_DB, ODOO_PASSWORD, ODOO_URL, get_odoo_connection

HELPDESK_TEAM_ID = 2
BASE_TICKET_DOMAIN: List[Any] = [
    ("team_id", "=", HELPDESK_TEAM_ID),
    ("stage_id.name", "not ilike", "cancel"),
]

# Odoo 17 subscription SO states considered "running"
ACTIVE_SUBSCRIPTION_STATES = ("3_progress", "4_paused")

SO_STATE_WON = "sale"


def _base_url() -> str:
    return (ODOO_URL or "").rstrip("/")


def partner_form_url(partner_id: int) -> str:
    return f"{_base_url()}/web#id={partner_id}&model=res.partner&view_type=form"


def _partner_location(partner: Dict[str, Any]) -> Dict[str, Any]:
    """Structured address and a single-line location string for reports."""
    street = (partner.get("street") or "").strip()
    street2 = (partner.get("street2") or "").strip()
    city = (partner.get("city") or "").strip()
    zip_code = (partner.get("zip") or "").strip()
    state = partner.get("state_id")
    country = partner.get("country_id")
    state_name = state[1] if state else None
    country_name = country[1] if country else None

    city_line = " ".join(p for p in [zip_code, city] if p).strip()
    parts = [p for p in [street, street2, city_line, state_name, country_name] if p]
    display = ", ".join(parts) if parts else None

    return {
        "street": street or None,
        "street2": street2 or None,
        "city": city or None,
        "zip": zip_code or None,
        "state": state_name,
        "country": country_name,
        "location_display": display,
    }


def sale_order_url(order_id: int) -> str:
    return f"{_base_url()}/web#id={order_id}&model=sale.order&view_type=form"


def lead_form_url(lead_id: int) -> str:
    return f"{_base_url()}/web#id={lead_id}&model=crm.lead&view_type=form"


def project_url(project_id: int) -> str:
    return f"{_base_url()}/web#id={project_id}&model=project.project&view_type=form"


def ticket_url(ticket_id: int) -> str:
    return f"{_base_url()}/web#id={ticket_id}&model=helpdesk.ticket&view_type=form"


def _partner_child_domain(field: str, partner_id: int) -> List[Any]:
    return [(field, "child_of", partner_id)]


def resolve_partners_by_name(name: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Search companies (commercial_partner_id), deduplicated — same semantics as sales MCP."""
    q = (name or "").strip()
    if not q:
        return []
    uid, models = get_odoo_connection()
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
        {"limit": limit * 3, "order": "name"},
    )
    if not partner_ids:
        return []
    rows = models.execute_kw(
        ODOO_DB,
        uid,
        ODOO_PASSWORD,
        "res.partner",
        "read",
        [partner_ids],
        {"fields": ["id", "name", "commercial_partner_id", "is_company"]},
    )
    seen: set = set()
    out: List[Dict[str, Any]] = []
    for r in rows:
        cp = r.get("commercial_partner_id")
        company_id = int(cp[0]) if cp else int(r["id"])
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
                {"fields": ["id", "name"]},
            )
            cname = companies[0]["name"] if companies else ""
        else:
            cname = r.get("name") or ""
        out.append(
            {
                "partner_id": company_id,
                "name": cname,
                "url": partner_form_url(company_id),
            }
        )
        if len(out) >= limit:
            break
    return out


def _read_order_lines(models: Any, uid: int, order_ids: List[int]) -> Dict[int, List[Dict[str, Any]]]:
    if not order_ids:
        return {}
    line_ids: List[int] = []
    orders = models.execute_kw(
        ODOO_DB,
        uid,
        ODOO_PASSWORD,
        "sale.order",
        "read",
        [order_ids],
        {"fields": ["order_line"]},
    )
    for o in orders:
        line_ids.extend(o.get("order_line") or [])
    if not line_ids:
        return {}
    lines = models.execute_kw(
        ODOO_DB,
        uid,
        ODOO_PASSWORD,
        "sale.order.line",
        "read",
        [line_ids],
        {"fields": ["id", "order_id", "name", "product_id", "product_uom_qty", "price_subtotal"]},
    )
    by_order: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for ln in lines:
        oid = ln["order_id"][0] if ln.get("order_id") else None
        if not oid:
            continue
        prod = ln.get("product_id")
        by_order[oid].append(
            {
                "description": html_to_plain_text(ln.get("name") or ""),
                "product": prod[1] if prod else None,
                "qty": ln.get("product_uom_qty"),
                "subtotal": ln.get("price_subtotal"),
            }
        )
    return by_order


def _format_so(so: Dict[str, Any], lines: List[Dict[str, Any]]) -> Dict[str, Any]:
    oid = so["id"]
    return {
        "order_id": oid,
        "name": so.get("name") or "",
        "date_order": so.get("date_order"),
        "state": so.get("state"),
        "amount_total": so.get("amount_total"),
        "amount_untaxed": so.get("amount_untaxed"),
        "note": html_to_plain_text(so.get("note") or ""),
        "internal_note": html_to_plain_text(so.get("internal_note") or ""),
        "url": sale_order_url(oid),
        "lines": lines,
    }


def fetch_crm_summary(partner_id: int) -> Dict[str, Any]:
    uid, models = get_odoo_connection()
    lead_domain = _partner_child_domain("partner_id", partner_id)
    lead_ids = models.execute_kw(
        ODOO_DB,
        uid,
        ODOO_PASSWORD,
        "crm.lead",
        "search",
        [lead_domain],
        {"limit": 30, "order": "write_date desc"},
    )
    leads: List[Dict[str, Any]] = []
    if lead_ids:
        raw = models.execute_kw(
            ODOO_DB,
            uid,
            ODOO_PASSWORD,
            "crm.lead",
            "read",
            [lead_ids],
            {"fields": ["id", "name", "stage_id", "create_date", "write_date"]},
        )
        for r in raw:
            leads.append(
                {
                    "lead_id": r["id"],
                    "name": r.get("name") or "",
                    "stage": r["stage_id"][1] if r.get("stage_id") else None,
                    "create_date": r.get("create_date"),
                    "url": lead_form_url(r["id"]),
                }
            )

    messages_out: List[Dict[str, Any]] = []
    if lead_ids:
        msg_domain = [
            ("model", "=", "crm.lead"),
            ("res_id", "in", lead_ids),
            ("message_type", "!=", "notification"),
        ]
        msgs = models.execute_kw(
            ODOO_DB,
            uid,
            ODOO_PASSWORD,
            "mail.message",
            "search_read",
            [msg_domain],
            {
                "fields": ["date", "author_id", "body", "res_id", "subject"],
                "limit": 200,
                "order": "date desc",
            },
        )
        lead_names = {l["lead_id"]: l["name"] for l in leads}
        for m in msgs:
            rid = m.get("res_id")
            body = html_to_plain_text(m.get("body") or "")
            if not body.strip():
                continue
            messages_out.append(
                {
                    "date": m.get("date"),
                    "author": m["author_id"][1] if m.get("author_id") else None,
                    "lead_id": rid,
                    "lead_name": lead_names.get(rid),
                    "subject": m.get("subject"),
                    "body": body[:4000],
                    "url": lead_form_url(rid) if rid else None,
                }
            )

    return {"leads": leads, "opportunity_messages": messages_out, "lead_count": len(leads)}


def fetch_original_sale(partner_id: int) -> Dict[str, Any]:
    uid, models = get_odoo_connection()
    domain = _partner_child_domain("partner_id", partner_id) + [
        ("state", "=", SO_STATE_WON),
        ("is_subscription", "=", False),
    ]
    order_ids = models.execute_kw(
        ODOO_DB,
        uid,
        ODOO_PASSWORD,
        "sale.order",
        "search",
        [domain],
        {"limit": 1, "order": "date_order asc"},
    )
    if not order_ids:
        return {"found": False}
    orders = models.execute_kw(
        ODOO_DB,
        uid,
        ODOO_PASSWORD,
        "sale.order",
        "read",
        [order_ids],
        {
            "fields": [
                "id",
                "name",
                "date_order",
                "state",
                "amount_total",
                "amount_untaxed",
                "note",
                "internal_note",
            ]
        },
    )
    lines_by = _read_order_lines(models, uid, order_ids)
    return {"found": True, "order": _format_so(orders[0], lines_by.get(order_ids[0], []))}


def fetch_subscriptions(partner_id: int) -> Dict[str, Any]:
    uid, models = get_odoo_connection()
    domain = _partner_child_domain("partner_id", partner_id) + [
        ("is_subscription", "=", True),
        ("subscription_state", "in", list(ACTIVE_SUBSCRIPTION_STATES)),
    ]
    order_ids = models.execute_kw(
        ODOO_DB,
        uid,
        ODOO_PASSWORD,
        "sale.order",
        "search",
        [domain],
        {"order": "date_order desc", "limit": 20},
    )
    if not order_ids:
        return {"active_count": 0, "subscriptions": []}
    orders = models.execute_kw(
        ODOO_DB,
        uid,
        ODOO_PASSWORD,
        "sale.order",
        "read",
        [order_ids],
        {
            "fields": [
                "id",
                "name",
                "date_order",
                "state",
                "subscription_state",
                "recurring_monthly",
                "recurring_total",
                "start_date",
                "end_date",
                "amount_total",
                "note",
                "internal_note",
                "recurring_details",
                "main_modules",
                "software",
                "main_integrations",
                "user_partner",
            ]
        },
    )
    lines_by = _read_order_lines(models, uid, order_ids)
    fg = models.execute_kw(
        ODOO_DB,
        uid,
        ODOO_PASSWORD,
        "sale.order",
        "fields_get",
        [["subscription_state"]],
        {"attributes": ["selection"]},
    )
    state_labels = dict(fg.get("subscription_state", {}).get("selection", []))

    subs = []
    for o in orders:
        oid = o["id"]
        sub_state = o.get("subscription_state")
        sw = o.get("software")
        up = o.get("user_partner")
        subs.append(
            {
                **_format_so(o, lines_by.get(oid, [])),
                "subscription_state": sub_state,
                "subscription_state_label": state_labels.get(sub_state, sub_state),
                "recurring_monthly": o.get("recurring_monthly"),
                "recurring_total": o.get("recurring_total"),
                "start_date": o.get("start_date"),
                "end_date": o.get("end_date"),
                "recurring_details": html_to_plain_text(o.get("recurring_details") or ""),
                "main_modules": (o.get("main_modules") or "").strip() or None,
                "software": sw[1] if sw else None,
                "software_id": sw[0] if sw else None,
                "main_integrations": (o.get("main_integrations") or "").strip() or None,
                "user_partner": up[1] if up else None,
                "user_partner_id": up[0] if up else None,
            }
        )
    return {"active_count": len(subs), "subscriptions": subs}


def fetch_projects(partner_id: int, years_back: int) -> Dict[str, Any]:
    uid, models = get_odoo_connection()
    start_date = (datetime.now() - timedelta(days=365 * years_back)).strftime("%Y-%m-%d")
    project_ids = models.execute_kw(
        ODOO_DB,
        uid,
        ODOO_PASSWORD,
        "project.project",
        "search",
        [[("partner_id", "child_of", partner_id)]],
        {"limit": 50},
    )
    if not project_ids:
        return {
            "project_count": 0,
            "projects": [],
            "total_customer_hours": 0.0,
            "top_tasks": [],
            "by_employee": [],
        }

    projects_raw = models.execute_kw(
        ODOO_DB,
        uid,
        ODOO_PASSWORD,
        "project.project",
        "read",
        [project_ids],
        {"fields": ["id", "name", "date_start", "date"]},
    )
    projects = [
        {
            "project_id": p["id"],
            "name": p.get("name") or "",
            "url": project_url(p["id"]),
        }
        for p in projects_raw
    ]

    ts_domain = [
        ("project_id", "in", project_ids),
        ("date", ">=", start_date),
        ("so_line", "!=", False),
    ]
    lines = models.execute_kw(
        ODOO_DB,
        uid,
        ODOO_PASSWORD,
        "account.analytic.line",
        "search_read",
        [ts_domain],
        {"fields": ["unit_amount", "employee_id", "task_id", "project_id"], "limit": 8000},
    )
    total_h = round(sum(l.get("unit_amount") or 0 for l in lines), 2)
    by_emp: Dict[str, float] = defaultdict(float)
    by_task: Dict[int, float] = defaultdict(float)
    for l in lines:
        h = l.get("unit_amount") or 0
        if l.get("employee_id"):
            by_emp[l["employee_id"][1]] += h
        if l.get("task_id"):
            by_task[l["task_id"][0]] += h

    by_employee = [
        {"employee": name, "hours": round(h, 2)}
        for name, h in sorted(by_emp.items(), key=lambda x: -x[1])[:15]
    ]

    top_tasks: List[Dict[str, Any]] = []
    if by_task:
        task_ids = list(by_task.keys())
        tasks = models.execute_kw(
            ODOO_DB,
            uid,
            ODOO_PASSWORD,
            "project.task",
            "read",
            [task_ids],
            {"fields": ["id", "name", "project_id", "stage_id"]},
        )
        for t in tasks:
            tid = t["id"]
            top_tasks.append(
                {
                    "task_id": tid,
                    "name": t.get("name") or "",
                    "project": t["project_id"][1] if t.get("project_id") else None,
                    "stage": t["stage_id"][1] if t.get("stage_id") else None,
                    "hours": round(by_task[tid], 2),
                    "url": f"{_base_url()}/web#id={tid}&model=project.task&view_type=form",
                }
            )
        top_tasks.sort(key=lambda x: -x["hours"])
        top_tasks = top_tasks[:15]

    return {
        "project_count": len(projects),
        "projects": projects,
        "total_customer_hours": total_h,
        "top_tasks": top_tasks,
        "by_employee": by_employee,
        "period_start": start_date,
    }


def fetch_helpdesk(partner_id: int, years_back: int) -> Dict[str, Any]:
    uid, models = get_odoo_connection()
    start_dt = (datetime.now() - timedelta(days=365 * years_back)).strftime("%Y-%m-%d 00:00:00")
    domain = BASE_TICKET_DOMAIN + _partner_child_domain("partner_id", partner_id) + [
        ("create_date", ">=", start_dt),
    ]
    ticket_ids = models.execute_kw(
        ODOO_DB,
        uid,
        ODOO_PASSWORD,
        "helpdesk.ticket",
        "search",
        [domain],
        {"order": "create_date desc", "limit": 500},
    )
    if not ticket_ids:
        return {
            "ticket_count": 0,
            "by_tag": [],
            "recent_tickets": [],
            "period_start": start_dt,
        }

    tickets = models.execute_kw(
        ODOO_DB,
        uid,
        ODOO_PASSWORD,
        "helpdesk.ticket",
        "read",
        [ticket_ids],
        {"fields": ["id", "name", "description", "stage_id", "create_date", "tag_ids"]},
    )
    all_tag_ids: set = set()
    for t in tickets:
        all_tag_ids.update(t.get("tag_ids") or [])
    tag_map: Dict[int, str] = {}
    if all_tag_ids:
        tags = models.execute_kw(
            ODOO_DB,
            uid,
            ODOO_PASSWORD,
            "helpdesk.tag",
            "read",
            [list(all_tag_ids)],
            {"fields": ["id", "name"]},
        )
        tag_map = {t["id"]: t["name"] for t in tags}

    tag_counts: Dict[str, int] = defaultdict(int)
    recent: List[Dict[str, Any]] = []
    for t in tickets:
        tnames = [tag_map.get(tid) for tid in (t.get("tag_ids") or []) if tid in tag_map]
        for tn in tnames:
            if tn:
                tag_counts[tn] += 1
        recent.append(
            {
                "ticket_id": t["id"],
                "name": t.get("name") or "",
                "stage": t["stage_id"][1] if t.get("stage_id") else None,
                "create_date": t.get("create_date"),
                "tag_names": tnames,
                "description": html_to_plain_text(t.get("description") or "")[:1500],
                "url": ticket_url(t["id"]),
            }
        )

    by_tag = [
        {"tag": name, "count": cnt}
        for name, cnt in sorted(tag_counts.items(), key=lambda x: -x[1])
    ]

    return {
        "ticket_count": len(tickets),
        "by_tag": by_tag,
        "recent_tickets": recent[:25],
        "period_start": start_dt,
    }


def build_client_summary(partner_id: int, years_back: int = 5) -> Dict[str, Any]:
    uid, models = get_odoo_connection()
    partners = models.execute_kw(
        ODOO_DB,
        uid,
        ODOO_PASSWORD,
        "res.partner",
        "read",
        [[partner_id]],
        {
            "fields": [
                "id",
                "name",
                "street",
                "street2",
                "city",
                "zip",
                "state_id",
                "country_id",
            ]
        },
    )
    if not partners:
        return {"error": f"Partner id {partner_id} not found."}
    p = partners[0]
    pname = p.get("name") or ""
    location = _partner_location(p)

    result: Dict[str, Any] = {
        "partner_id": partner_id,
        "partner_name": pname,
        "partner_url": partner_form_url(partner_id),
        "location": location,
        "location_display": location.get("location_display"),
        "years_back": years_back,
        "errors": {},
    }

    sections: List[Tuple[str, Any]] = [
        ("crm", lambda: fetch_crm_summary(partner_id)),
        ("original_sale", lambda: fetch_original_sale(partner_id)),
        ("subscriptions", lambda: fetch_subscriptions(partner_id)),
        ("projects", lambda: fetch_projects(partner_id, years_back)),
        ("helpdesk", lambda: fetch_helpdesk(partner_id, years_back)),
    ]
    for key, fn in sections:
        try:
            result[key] = fn()
        except Exception as e:
            result["errors"][key] = str(e)
            result[key] = None

    # Support hours: reuse project customer hours in same period for convenience
    proj = result.get("projects") or {}
    hd = result.get("helpdesk") or {}
    result["support_hours_on_projects"] = proj.get("total_customer_hours", 0.0)
    result["helpdesk"] = hd

    return result
