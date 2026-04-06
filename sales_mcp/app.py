"""Odoo Sales Capture MCP — search companies/leads and log notes from pasted text + footer."""

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastmcp import FastMCP
from starlette.responses import JSONResponse

load_dotenv()

from sales_mcp.odoo_sales import (
    lead_form_url,
    log_activity_on_record,
    partner_form_url,
    resolve_salesperson_user_id,
    search_leads,
    search_partners_company_normalized,
    strip_trailing_disclaimer,
    today_yyyy_mm_dd,
)
from sales_mcp.paste_footer import parse_paste_footer

SERVER_VERSION = "2026-04-06"
SERVER_AUTHOR = "Svante"
SERVER_START_TIME = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

mcp = FastMCP("Odoo Sales Capture")

_OCCURRED_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_occurred_on(value: Optional[str]) -> str:
    if value is None or not str(value).strip():
        return today_yyyy_mm_dd()
    s = str(value).strip()
    if not _OCCURRED_RE.match(s):
        raise ValueError(f"occurred_on must be YYYY-MM-DD, got: {value!r}")
    return s


@mcp.tool()
def search_partner(query: str, limit: int = 20) -> List[Dict[str, Any]]:
    """
    Search Odoo contacts (res.partner) and return **companies** only: each row is the
    commercial entity (`commercial_partner_id`), deduplicated. Use **name, email, or phone**
    in `query`.

    **Workflow:** Call this after the user pastes text with `+ add to partner` and confirms
    you should search. If zero results, tell them no matching **company** was found. If
    several, show options with `url` and **ask which company** to use before calling `log_note`.
    """
    try:
        return search_partners_company_normalized(query, limit=limit)
    except Exception as e:
        return [{"error": str(e)}]


@mcp.tool()
def search_lead(query: str, limit: int = 15) -> List[Dict[str, Any]]:
    """
    Search CRM opportunities (`crm.lead`) by name or partner name.

    **Workflow:** For `+ add to opportunity`, search then confirm the right opportunity with
    the user (use `url`) before calling `log_note`.
    """
    try:
        return search_leads(query, limit=limit)
    except Exception as e:
        return [{"error": str(e)}]


@mcp.tool()
def log_note(
    full_text: str,
    salesperson_email: str,
    interaction_type: str = "call",
    partner_id: Optional[int] = None,
    opportunity_id: Optional[int] = None,
    occurred_on: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Writes to **Odoo CRM** from pasted text whose **last line** is `+ add to partner` or
    `+ add to opportunity` (case-insensitive; spaces after `+` allowed). Everything above
    that line is the note body. Strips a trailing AI/vendor disclaimer when present.

    **Only call after the user confirmed** the company (`partner_id`) or opportunity
    (`opportunity_id`) from `search_partner` / `search_lead`.

    **interaction_type:** `call` (default) or `meeting` — maps to Odoo activity types
    (names configurable via `ODOO_CALL_ACTIVITY_TYPE_NAME` / `ODOO_MEETING_ACTIVITY_TYPE_NAME`).

    **occurred_on:** `YYYY-MM-DD` when the call/meeting happened; omit to use today
    (Europe/Helsinki via `ODOO_SALES_DATE_TZ`). Parse Finnish `Vastattu` / `Soitettu` lines
    in the paste and pass the date here.

    **partner_id** must be the **company** id returned by `search_partner`, not a child contact.
    """
    try:
        it = (interaction_type or "call").strip().lower()
        if it not in ("call", "meeting"):
            return {"error": "interaction_type must be 'call' or 'meeting'."}

        body, target = parse_paste_footer(full_text)
        body = strip_trailing_disclaimer(body)
        if not body.strip():
            return {"error": "Note body is empty after parsing footer and disclaimer strip."}

        deadline = _validate_occurred_on(occurred_on)
        user_id = resolve_salesperson_user_id(salesperson_email)

        if target == "partner":
            if partner_id is None:
                return {
                    "error": "Footer is + add to partner but partner_id is missing. "
                    "Search with search_partner, confirm the company, then pass partner_id."
                }
            if opportunity_id is not None:
                return {
                    "error": "Do not pass opportunity_id when footer is + add to partner."
                }
            log_activity_on_record(
                "res.partner",
                int(partner_id),
                it,
                user_id,
                body,
                deadline,
            )
            return {
                "ok": True,
                "target": "partner",
                "partner_id": partner_id,
                "url": partner_form_url(int(partner_id)),
                "interaction_type": it,
                "occurred_on": deadline,
            }

        if partner_id is not None:
            return {"error": "Do not pass partner_id when footer is + add to opportunity."}
        if opportunity_id is None:
            return {
                "error": "Footer is + add to opportunity but opportunity_id is missing. "
                "Search with search_lead, confirm, then pass opportunity_id."
            }
        log_activity_on_record(
            "crm.lead",
            int(opportunity_id),
            it,
            user_id,
            body,
            deadline,
        )
        return {
            "ok": True,
            "target": "opportunity",
            "opportunity_id": opportunity_id,
            "url": lead_form_url(int(opportunity_id)),
            "interaction_type": it,
            "occurred_on": deadline,
        }
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"Odoo error: {e}"}


@mcp.custom_route("/", methods=["GET"])
async def index(_request):
    return JSONResponse(
        {
            "status": "ok",
            "service": "Odoo Sales Capture",
            "version": SERVER_VERSION,
            "author": SERVER_AUTHOR,
            "server_start_time": SERVER_START_TIME,
            "mcp_ready": True,
        }
    )
