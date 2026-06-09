"""Odoo project.update — fetch and format project status updates."""

from __future__ import annotations

import calendar
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from html_util import html_to_plain_text
from odoo_connection import ODOO_DB, ODOO_PASSWORD, ODOO_URL, get_odoo_connection

_logger = logging.getLogger(__name__)

SLACK_SUMMARY_MAX = 2500

STATUS_LABELS = {
    "on_track": "On Track",
    "at_risk": "At Risk",
    "off_track": "Off Track",
    "on_hold": "On Hold",
    "done": "Done",
}

UPDATE_FIELDS = [
    "name",
    "date",
    "status",
    "progress",
    "progress_percentage",
    "user_id",
    "project_id",
    "description",
    "closed_task_count",
    "task_count",
    "closed_task_percentage",
    "timesheet_time",
    "timesheet_percentage",
    "allocated_time",
]


def _base_url() -> str:
    return (ODOO_URL or "").rstrip("/")


def project_url(project_id: int) -> str:
    return f"{_base_url()}/web#id={project_id}&model=project.project&view_type=form"


def update_url(update_id: int) -> str:
    return f"{_base_url()}/web#id={update_id}&model=project.update&view_type=form"


def _format_date(date_str: Optional[str]) -> str:
    if not date_str:
        return ""
    try:
        d = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
        return f"{d.day} {calendar.month_abbr[d.month]} {d.year}"
    except (ValueError, TypeError):
        return date_str[:10]


def _status_label(status: Optional[str]) -> str:
    if not status:
        return "—"
    return STATUS_LABELS.get(status, status.replace("_", " ").title())


def _normalize_update(raw: Dict[str, Any]) -> Dict[str, Any]:
    author = raw.get("user_id")
    project = raw.get("project_id")
    return {
        "id": raw["id"],
        "name": raw.get("name") or "",
        "date": raw.get("date"),
        "date_display": _format_date(raw.get("date")),
        "status": raw.get("status"),
        "status_label": _status_label(raw.get("status")),
        "progress": raw.get("progress") or 0,
        "progress_percentage": raw.get("progress_percentage") or 0.0,
        "author": author[1] if author else None,
        "author_id": author[0] if author else None,
        "project_id": project[0] if project else None,
        "project_name": project[1] if project else None,
        "closed_task_count": raw.get("closed_task_count") or 0,
        "task_count": raw.get("task_count") or 0,
        "closed_task_percentage": raw.get("closed_task_percentage") or 0,
        "timesheet_time": raw.get("timesheet_time") or 0,
        "timesheet_percentage": raw.get("timesheet_percentage") or 0,
        "allocated_time": raw.get("allocated_time") or 0,
        "description_plain": html_to_plain_text(raw.get("description") or ""),
        "url": update_url(raw["id"]),
    }


def search_projects(name_filter: str = "") -> Dict[str, Any]:
    try:
        uid, models = get_odoo_connection()
        domain: List[Any] = []
        if name_filter.strip():
            domain.append(("name", "ilike", name_filter.strip()))
        projects = models.execute_kw(
            ODOO_DB,
            uid,
            ODOO_PASSWORD,
            "project.project",
            "search_read",
            [domain],
            {"fields": ["id", "name", "partner_id"], "order": "name", "limit": 25},
        )
        return {
            "projects": [
                {
                    "id": p["id"],
                    "name": p["name"],
                    "partner": p["partner_id"][1] if p.get("partner_id") else None,
                    "url": project_url(p["id"]),
                }
                for p in projects
            ]
        }
    except Exception as e:
        _logger.error("search_projects: %s", e)
        return {"error": str(e)}


def resolve_project(
    project_id: Optional[int] = None,
    project_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Resolve a single project or return ambiguous/error."""
    if not project_id and not (project_name or "").strip():
        return {"error": "Provide project_id or project_name."}

    try:
        uid, models = get_odoo_connection()
        if project_id:
            rows = models.execute_kw(
                ODOO_DB,
                uid,
                ODOO_PASSWORD,
                "project.project",
                "read",
                [[project_id]],
                {"fields": ["id", "name", "partner_id"]},
            )
            if not rows:
                return {"error": f"No project with id {project_id}."}
            p = rows[0]
            return {
                "id": p["id"],
                "name": p["name"],
                "partner": p["partner_id"][1] if p.get("partner_id") else None,
                "url": project_url(p["id"]),
            }

        name = project_name.strip()
        found = models.execute_kw(
            ODOO_DB,
            uid,
            ODOO_PASSWORD,
            "project.project",
            "search_read",
            [[("name", "ilike", name)]],
            {"fields": ["id", "name", "partner_id"], "limit": 10},
        )
        if not found:
            return {"error": f"No project found matching {name!r}."}
        if len(found) == 1:
            p = found[0]
            return {
                "id": p["id"],
                "name": p["name"],
                "partner": p["partner_id"][1] if p.get("partner_id") else None,
                "url": project_url(p["id"]),
            }
        exact = [p for p in found if p["name"].lower() == name.lower()]
        if len(exact) == 1:
            p = exact[0]
            return {
                "id": p["id"],
                "name": p["name"],
                "partner": p["partner_id"][1] if p.get("partner_id") else None,
                "url": project_url(p["id"]),
            }
        return {
            "ambiguous": True,
            "message": "Multiple projects match; be more specific or use project_id.",
            "matches": [
                {"id": p["id"], "name": p["name"], "url": project_url(p["id"])}
                for p in found
            ],
        }
    except Exception as e:
        _logger.error("resolve_project: %s", e)
        return {"error": str(e)}


def resolve_slack_project(text: str) -> Dict[str, Any]:
    """Parse /projectupdate slash command text."""
    raw = (text or "").strip()
    if not raw:
        return {
            "error": "usage",
            "message": "Usage: `/projectupdate 2045` or `/projectupdate OdooFinance`",
        }
    if re.fullmatch(r"\d+", raw):
        return {"project_id": int(raw)}
    return {"project_name": raw}


def _fetch_updates(
    models,
    uid: int,
    project_id: int,
    limit: int = 1,
    update_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    if update_id:
        rows = models.execute_kw(
            ODOO_DB,
            uid,
            ODOO_PASSWORD,
            "project.update",
            "read",
            [[update_id]],
            {"fields": UPDATE_FIELDS},
        )
        if not rows:
            return []
        if rows[0].get("project_id") and rows[0]["project_id"][0] != project_id:
            return []
        return [_normalize_update(rows[0])]

    rows = models.execute_kw(
        ODOO_DB,
        uid,
        ODOO_PASSWORD,
        "project.update",
        "search_read",
        [[("project_id", "=", project_id)]],
        {"fields": UPDATE_FIELDS, "order": "date desc, id desc", "limit": max(1, min(limit, 10))},
    )
    return [_normalize_update(r) for r in rows]


def format_project_update_slack(data: Dict[str, Any]) -> str:
    if data.get("error"):
        if data.get("error") == "usage":
            return data.get("message", "Usage: /projectupdate 2045 | project name")
        return f":warning: {data['error']}"
    if data.get("ambiguous"):
        lines = [f":warning: {data.get('message', 'Ambiguous')}"]
        for m in data.get("matches") or []:
            lines.append(f"  • [{m['name']}]({m.get('url', '')}) (id {m['id']})")
        return "\n".join(lines)

    project = data.get("project") or {}
    updates = data.get("updates") or []
    if not updates:
        return f":warning: No project updates found for {project.get('name', 'project')}."

    u = updates[0]
    lines = [
        f"*{project.get('name', '')}* — {u['name']}",
        f"{u['status_label']} · {u['date_display']} · {u.get('author') or '—'}",
        (
            f"Tasks: {u['closed_task_count']}/{u['task_count']} ({u['closed_task_percentage']}%)"
            f" · Timesheets: {u['timesheet_time']} h · Progress: {u['progress']}%"
        ),
        f"<{u['url']}|Open in Odoo>",
    ]
    summary = (u.get("description_plain") or "").strip()
    if summary:
        if len(summary) > SLACK_SUMMARY_MAX:
            summary = summary[: SLACK_SUMMARY_MAX - 3].rstrip() + "..."
        lines.append("")
        lines.append("*Summary:*")
        lines.append(summary)
    return "\n".join(lines)


def get_project_update(
    project_id: Optional[int] = None,
    project_name: Optional[str] = None,
    limit: int = 1,
    update_id: Optional[int] = None,
    format: str = "json",
) -> Union[Dict[str, Any], str]:
    project = resolve_project(project_id=project_id, project_name=project_name)
    if project.get("error") or project.get("ambiguous"):
        if format == "slack":
            return format_project_update_slack(project)
        return project

    try:
        uid, models = get_odoo_connection()
        updates = _fetch_updates(
            models, uid, project["id"], limit=limit, update_id=update_id
        )
        if update_id and not updates:
            err = {"error": f"Update {update_id} not found for this project."}
            return format_project_update_slack(err) if format == "slack" else err

        data = {
            "project": project,
            "updates": updates,
            "update_count": len(updates),
        }
        if format == "slack":
            return format_project_update_slack(data)
        return data
    except Exception as e:
        _logger.error("get_project_update: %s", e)
        err = {"error": str(e)}
        return format_project_update_slack(err) if format == "slack" else err
