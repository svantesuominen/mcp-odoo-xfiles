"""Coverage 1 — pipeline workload vs capacity (team / person)."""

from __future__ import annotations

import calendar
import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union

from odoo_connection import ODOO_DB, ODOO_PASSWORD, get_odoo_connection

_logger = logging.getLogger(__name__)

VELOCITY_NOTE = (
    "Velocity = 3-month avg h/day on project-task timesheets (days with logged work)."
)

PIPELINE_STAGE_TERMS = [
    "backlog",
    "in progress",
    "code review",
    "acceptance",
    "ready for production",
]

DEFAULT_HOURS_PER_DAY = 7.5
MIN_VELOCITY_H_PER_DAY = 0.5

# Slack / MCP aliases → hr.department id (+ optional extra res.users for tasks)
TEAM_ALIASES: Dict[str, Dict[str, Any]] = {
    "xfiles": {"team_id": 18, "extra_user_ids": [67]},
    "x-files": {"team_id": 18, "extra_user_ids": [67]},
    "continuous services": {"team_id": 18, "extra_user_ids": [67]},
    "devteam": {"team_id": 12},
    "dev-team": {"team_id": 12},
    "dev": {"team_id": 12},
    "pmteam": {"team_id": 14},
    "pm-team": {"team_id": 14},
    "pm": {"team_id": 14},
    "ateam": {"team_id": 10},
    "a-team": {"team_id": 10},
    "mms": {"team_id": 16},
    "m-and-ms": {"team_id": 16},
}


def _month_key(d: date) -> str:
    return d.strftime("%Y-%m")


def _month_label(month_key: str) -> str:
    y, m = month_key.split("-")
    return f"{calendar.month_abbr[int(m)]}"


def _three_month_velocity_window(ref: date) -> Tuple[date, date]:
    """Previous 3 full calendar months ending before ref's month."""
    first_this = ref.replace(day=1)
    end = first_this - timedelta(days=1)
    y, m = end.year, end.month
    m -= 2
    while m < 1:
        m += 12
        y -= 1
    return date(y, m, 1), end


def _iter_workdays(start: date, end: date) -> List[date]:
    days: List[date] = []
    cur = start
    while cur <= end:
        if cur.weekday() < 5:
            days.append(cur)
        cur += timedelta(days=1)
    return days


def _format_velocity_label(
    progress_h: float, win_start: date, win_end: date, days_worked: int, total_hours: float
) -> str:
    label = f"{_month_label(_month_key(win_start))}–{_month_label(_month_key(win_end))} {win_end.year}"
    return (
        f"velocity {progress_h:.1f} h/day ({label} · {days_worked} days worked · "
        f"{round(total_hours, 0):.0f} h on tasks)"
    )


def _sum_capacity(month_rows: List[Dict[str, Any]]) -> float:
    return round(sum(r.get("capacity_hours") or 0 for r in month_rows), 1)


def _format_month_coverage_bits(month_rows: List[Dict[str, Any]]) -> str:
    """e.g. May 100% (120h avail), Jun 33% (85h avail)"""
    parts = []
    for row in month_rows:
        cap = row.get("capacity_hours") or 0
        parts.append(f"{row['month_label']} {row['coverage_pct']}% ({cap:.0f}h avail)")
    return ", ".join(parts)


def _format_planned_capacity_summary(planned: float, capacity: float) -> str:
    return f"planned {planned:.0f} h · available {capacity:.0f} h (3 mo)"


def _velocity_hpd(member: Dict[str, Any]) -> str:
    return f"{member.get('progress_hours_per_day', 0):.1f} h/d"


def _format_team_velocity_roster(members: List[Dict[str, Any]]) -> str:
    parts = [f"{m['name']} {_velocity_hpd(m)}" for m in members]
    return "Velocities: " + ", ".join(parts)


def _format_timeoff_block(leave_from: str, leave_to: str) -> str:
    """Compact fi-style range e.g. 5.7.–8.7."""
    try:
        d0 = datetime.strptime(leave_from[:10], "%Y-%m-%d").date()
        d1 = datetime.strptime(leave_to[:10], "%Y-%m-%d").date()
        return f"{d0.day}.{d0.month}.–{d1.day}.{d1.month}."
    except (ValueError, TypeError):
        return f"{leave_from[:10]} – {leave_to[:10]}"


def list_teams(name_filter: str = "") -> Dict[str, Any]:
    try:
        uid, models = get_odoo_connection()
        domain: List[Any] = []
        if name_filter.strip():
            domain.append(("name", "ilike", name_filter.strip()))
        depts = models.execute_kw(
            ODOO_DB,
            uid,
            ODOO_PASSWORD,
            "hr.department",
            "search_read",
            [domain],
            {"fields": ["id", "name", "member_ids"], "order": "name", "limit": 50},
        )
        teams = []
        for d in depts:
            member_ids = d.get("member_ids") or []
            names: List[str] = []
            if member_ids:
                emps = models.execute_kw(
                    ODOO_DB,
                    uid,
                    ODOO_PASSWORD,
                    "hr.employee",
                    "read",
                    [member_ids],
                    {"fields": ["name"]},
                )
                names = [e["name"] for e in emps]
            teams.append(
                {
                    "id": d["id"],
                    "name": d["name"],
                    "member_count": len(member_ids),
                    "member_names": names,
                }
            )
        return {"teams": teams, "aliases": sorted(TEAM_ALIASES.keys())}
    except Exception as e:
        _logger.error("list_teams: %s", e)
        return {"error": str(e)}


def _resolve_team(
    team_id: Optional[int],
    team_name: Optional[str],
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    uid, models = get_odoo_connection()
    if team_id:
        depts = models.execute_kw(
            ODOO_DB,
            uid,
            ODOO_PASSWORD,
            "hr.department",
            "read",
            [[team_id]],
            {"fields": ["id", "name"]},
        )
        if not depts:
            return None, f"No department with id {team_id}."
        return depts[0], None

    key = (team_name or "").strip().lower()
    if key in TEAM_ALIASES:
        cfg = TEAM_ALIASES[key]
        depts = models.execute_kw(
            ODOO_DB,
            uid,
            ODOO_PASSWORD,
            "hr.department",
            "read",
            [[cfg["team_id"]]],
            {"fields": ["id", "name"]},
        )
        if depts:
            return depts[0], None

    if team_name and team_name.strip():
        found = models.execute_kw(
            ODOO_DB,
            uid,
            ODOO_PASSWORD,
            "hr.department",
            "search_read",
            [[("name", "ilike", team_name.strip())]],
            {"fields": ["id", "name"], "limit": 10},
        )
        if len(found) == 1:
            return found[0], None
        if len(found) > 1:
            names = ", ".join(d["name"] for d in found)
            return None, f"Multiple departments match {team_name!r}: {names}"

    return None, "Team not found; use list_teams or a known alias (xfiles, devteam, pmteam)."


def _resolve_person(person_name: str) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    uid, models = get_odoo_connection()
    emps = models.execute_kw(
        ODOO_DB,
        uid,
        ODOO_PASSWORD,
        "hr.employee",
        "search_read",
        [[("name", "ilike", person_name.strip()), ("active", "=", True)]],
        {"fields": ["id", "name", "user_id", "department_id", "resource_calendar_id"], "limit": 10},
    )
    if not emps:
        return None, {"error": f"No employee found matching {person_name!r}.", "matches": []}
    if len(emps) > 1:
        exact = [e for e in emps if e["name"].lower() == person_name.strip().lower()]
        if len(exact) == 1:
            emps = exact
        else:
            return None, {
                "ambiguous": True,
                "message": "Multiple employees match; be more specific.",
                "matches": [{"id": e["id"], "name": e["name"]} for e in emps],
            }
    return emps[0], None


def resolve_slack_target(text: str) -> Dict[str, Any]:
    """Parse /coverage1 slash command text → team or person request."""
    raw = (text or "").strip()
    if not raw:
        return {
            "error": "usage",
            "message": (
                "Usage: `/coverage1 xfiles` | `devteam` | `pmteam` | "
                "`Firstname Lastname`"
            ),
        }
    key = raw.lower()
    if key in TEAM_ALIASES:
        cfg = TEAM_ALIASES[key]
        return {
            "mode": "team",
            "team_id": cfg["team_id"],
            "extra_user_ids": cfg.get("extra_user_ids") or [],
        }

    uid, models = get_odoo_connection()
    depts = models.execute_kw(
        ODOO_DB,
        uid,
        ODOO_PASSWORD,
        "hr.department",
        "search_read",
        [[("name", "ilike", raw)]],
        {"fields": ["id", "name"], "limit": 10},
    )
    if len(depts) == 1:
        return {"mode": "team", "team_id": depts[0]["id"], "extra_user_ids": []}
    if len(depts) > 1:
        return {
            "ambiguous": True,
            "message": "Multiple teams match.",
            "matches": [{"id": d["id"], "name": d["name"]} for d in depts],
        }

    emp, err = _resolve_person(raw)
    if err:
        return err
    return {"mode": "person", "employee_id": emp["id"]}


def _task_remaining_hours(task: Dict[str, Any]) -> float:
    r = task.get("remaining_hours")
    if r is not None and r > 0:
        return float(r)
    return max(0.0, float(task.get("allocated_hours") or 0.0))


def _pipeline_domain(user_ids: List[int]) -> List[Any]:
    stage_clauses: List[Any] = []
    for term in PIPELINE_STAGE_TERMS:
        stage_clauses.append(("stage_id.name", "ilike", term))
    domain: List[Any] = [("user_ids", "in", user_ids)]
    if len(stage_clauses) == 1:
        domain.extend(stage_clauses)
    else:
        domain.extend(["|"] * (len(stage_clauses) - 1))
        domain.extend(stage_clauses)
    return domain


def _fetch_members(
    team_id: int, extra_user_ids: Optional[List[int]] = None
) -> List[Dict[str, Any]]:
    uid, models = get_odoo_connection()
    emps = models.execute_kw(
        ODOO_DB,
        uid,
        ODOO_PASSWORD,
        "hr.employee",
        "search_read",
        [[("department_id", "=", team_id), ("active", "=", True)]],
        {
            "fields": ["id", "name", "user_id", "resource_calendar_id"],
            "limit": 200,
        },
    )
    members = []
    seen_users: set = set()
    for e in emps:
        if not e.get("user_id"):
            continue
        uid_val = e["user_id"][0]
        seen_users.add(uid_val)
        members.append(
            {
                "employee_id": e["id"],
                "user_id": uid_val,
                "name": e["name"],
                "resource_calendar_id": e.get("resource_calendar_id"),
            }
        )

    extra = extra_user_ids or []
    if extra:
        users = models.execute_kw(
            ODOO_DB,
            uid,
            ODOO_PASSWORD,
            "res.users",
            "read",
            [extra],
            {"fields": ["id", "name"]},
        )
        for u in users:
            if u["id"] in seen_users:
                continue
            seen_users.add(u["id"])
            emp = models.execute_kw(
                ODOO_DB,
                uid,
                ODOO_PASSWORD,
                "hr.employee",
                "search_read",
                [[("user_id", "=", u["id"])]],
                {"fields": ["id", "name", "resource_calendar_id"], "limit": 1},
            )
            if emp:
                members.append(
                    {
                        "employee_id": emp[0]["id"],
                        "user_id": u["id"],
                        "name": emp[0]["name"],
                        "resource_calendar_id": emp[0].get("resource_calendar_id"),
                    }
                )
            else:
                members.append(
                    {
                        "employee_id": None,
                        "user_id": u["id"],
                        "name": u["name"],
                        "resource_calendar_id": None,
                    }
                )
    return members


def _velocity_for_employee(employee_id: int, ref: date) -> Dict[str, Any]:
    uid, models = get_odoo_connection()
    win_start, win_end = _three_month_velocity_window(ref)
    lines = models.execute_kw(
        ODOO_DB,
        uid,
        ODOO_PASSWORD,
        "account.analytic.line",
        "search_read",
        [
            [
                ("employee_id", "=", employee_id),
                ("date", ">=", win_start.isoformat()),
                ("date", "<=", win_end.isoformat()),
                ("project_id", "!=", False),
                ("task_id", "!=", False),
            ]
        ],
        {"fields": ["unit_amount", "date"], "limit": 10000},
    )
    by_day: Dict[str, float] = {}
    for line in lines:
        d = line["date"]
        by_day[d] = by_day.get(d, 0.0) + (line.get("unit_amount") or 0.0)
    total = sum(by_day.values())
    days_worked = len(by_day)
    if days_worked:
        progress = max(MIN_VELOCITY_H_PER_DAY, round(total / days_worked, 2))
    else:
        progress = MIN_VELOCITY_H_PER_DAY
    label = _format_velocity_label(progress, win_start, win_end, days_worked, total)
    return {
        "progress_hours_per_day": progress,
        "velocity_window": {
            "start_date": win_start.isoformat(),
            "end_date": win_end.isoformat(),
            "days_worked": days_worked,
            "total_hours": round(total, 1),
        },
        "velocity_label": label,
    }


def _public_holiday_dates(
    models, uid, calendar_id: Optional[List], range_start: date, range_end: date
) -> set:
    """Workdays that are global/public leaves on the resource calendar."""
    if not calendar_id:
        return set()
    leaves = models.execute_kw(
        ODOO_DB,
        uid,
        ODOO_PASSWORD,
        "resource.calendar.leaves",
        "search_read",
        [
            [
                ("calendar_id", "=", calendar_id[0]),
                ("resource_id", "=", False),
                ("date_from", "<=", range_end.isoformat()),
                ("date_to", ">=", range_start.isoformat()),
            ]
        ],
        {"fields": ["date_from", "date_to"], "limit": 500},
    )
    holiday_dates: set = set()
    for lv in leaves:
        try:
            d0 = datetime.strptime(lv["date_from"][:10], "%Y-%m-%d").date()
            d1 = datetime.strptime(lv["date_to"][:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        for wd in _iter_workdays(max(d0, range_start), min(d1, range_end)):
            holiday_dates.add(wd)
    return holiday_dates


def _leave_days_in_range(
    models, uid, employee_id: int, range_start: date, range_end: date
) -> Tuple[float, List[Dict[str, str]]]:
    leaves = models.execute_kw(
        ODOO_DB,
        uid,
        ODOO_PASSWORD,
        "hr.leave",
        "search_read",
        [
            [
                ("employee_id", "=", employee_id),
                ("state", "=", "validate"),
                ("date_from", "<=", f"{range_end.isoformat()} 23:59:59"),
                ("date_to", ">=", f"{range_start.isoformat()} 00:00:00"),
            ]
        ],
        {"fields": ["date_from", "date_to", "number_of_days"], "limit": 100},
    )
    blocks: List[Dict[str, str]] = []
    total_days = 0.0
    for lv in leaves:
        total_days += float(lv.get("number_of_days") or 0.0)
        blocks.append({"from": lv["date_from"], "to": lv["date_to"]})
    return total_days, blocks


def _capacity_for_month(
    models,
    uid,
    employee_id: int,
    calendar_id: Optional[List],
    month_start: date,
    month_end: date,
    ref_today: date,
    progress_h: float,
) -> float:
    if month_start.year == ref_today.year and month_start.month == ref_today.month:
        wd_start = ref_today
    else:
        wd_start = month_start
    workdays = _iter_workdays(wd_start, month_end)
    if not workdays:
        return 0.0

    holidays = _public_holiday_dates(models, uid, calendar_id, wd_start, month_end)
    net_days = sum(1 for d in workdays if d not in holidays)

    leave_days, _ = _leave_days_in_range(models, uid, employee_id, wd_start, month_end)
    leave_days = min(leave_days, float(net_days))
    effective_days = max(0.0, net_days - leave_days)
    return round(effective_days * progress_h, 1)


def _planned_hours_per_user(
    models, uid, user_ids: List[int], team_user_ids: set
) -> Dict[int, float]:
    if not user_ids:
        return {}
    tasks = models.execute_kw(
        ODOO_DB,
        uid,
        ODOO_PASSWORD,
        "project.task",
        "search_read",
        [_pipeline_domain(user_ids)],
        {"fields": ["user_ids", "remaining_hours", "allocated_hours"], "limit": 5000},
    )
    person_hours: Dict[int, float] = {}
    for t in tasks:
        hours = _task_remaining_hours(t)
        if hours <= 0:
            continue
        assignees = [u for u in (t.get("user_ids") or []) if u in team_user_ids]
        if not assignees:
            continue
        share = hours / len(assignees)
        for u in assignees:
            person_hours[u] = round(person_hours.get(u, 0.0) + share, 1)
    return person_hours


def _month_range(months_ahead: int, ref: date) -> List[Tuple[str, date, date]]:
    result = []
    y, m = ref.year, ref.month
    for _ in range(months_ahead):
        last = calendar.monthrange(y, m)[1]
        start = date(y, m, 1)
        end = date(y, m, last)
        result.append((_month_key(start), start, end))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return result


def _waterfall_months(
    planned: float, capacity_by_month: List[float]
) -> List[Dict[str, Any]]:
    pile = planned
    rows = []
    for cap in capacity_by_month:
        workload = pile
        if cap > 0:
            pct = min(100, round(100 * workload / cap))
        else:
            pct = 100 if workload <= 0 else 0
        consumed = min(pile, cap) if cap > 0 else 0.0
        pile = round(max(0.0, pile - consumed), 1)
        rows.append(
            {
                "workload_hours": round(workload, 1),
                "capacity_hours": round(cap, 1),
                "coverage_pct": pct,
            }
        )
    return rows


def _build_member_coverage(
    member: Dict[str, Any],
    planned: float,
    month_specs: List[Tuple[str, date, date]],
    ref: date,
) -> Dict[str, Any]:
    uid, models = get_odoo_connection()
    emp_id = member["employee_id"]
    if not emp_id:
        return {
            "name": member["name"],
            "planned_hours": planned,
            "progress_hours_per_day": MIN_VELOCITY_H_PER_DAY,
            "velocity_window": {},
            "velocity_label": f"velocity {MIN_VELOCITY_H_PER_DAY} h/day (no employee record)",
            "time_off": [],
            "months": [],
            "error": "No hr.employee linked to this user",
        }

    vel = _velocity_for_employee(emp_id, ref)
    progress = vel["progress_hours_per_day"]
    cal_id = member.get("resource_calendar_id")

    capacities: List[float] = []
    for _, m_start, m_end in month_specs:
        cap = _capacity_for_month(
            models, uid, emp_id, cal_id, m_start, m_end, ref, progress
        )
        capacities.append(cap)

    wf = _waterfall_months(planned, capacities)
    time_off_labels: List[str] = []
    month_rows: List[Dict[str, Any]] = []
    for i, (month_key, m_start, m_end) in enumerate(month_specs):
        _, blocks = _leave_days_in_range(models, uid, emp_id, m_start, m_end)
        for b in blocks:
            lbl = _format_timeoff_block(b["from"], b["to"])
            if lbl not in time_off_labels:
                time_off_labels.append(lbl)
        month_rows.append(
            {
                "month": month_key,
                "month_label": _month_label(month_key),
                **wf[i],
            }
        )

    return {
        "name": member["name"],
        "employee_id": emp_id,
        "user_id": member["user_id"],
        "planned_hours": round(planned, 1),
        **vel,
        "time_off": time_off_labels,
        "months": month_rows,
    }


def compute_coverage1(
    team_id: Optional[int] = None,
    team_name: Optional[str] = None,
    person_name: Optional[str] = None,
    employee_id: Optional[int] = None,
    extra_user_ids: Optional[List[int]] = None,
    months: int = 3,
) -> Dict[str, Any]:
    ref = date.today()
    month_specs = _month_range(max(1, min(months, 6)), ref)
    month_keys = [m[0] for m in month_specs]

    try:
        uid, models = get_odoo_connection()

        if person_name or employee_id:
            if employee_id:
                emps = models.execute_kw(
                    ODOO_DB,
                    uid,
                    ODOO_PASSWORD,
                    "hr.employee",
                    "read",
                    [[employee_id]],
                    {"fields": ["id", "name", "user_id", "department_id", "resource_calendar_id"]},
                )
                if not emps:
                    return {"error": f"No employee id {employee_id}."}
                emp = emps[0]
            else:
                emp, err = _resolve_person(person_name or "")
                if err:
                    return err

            if not emp.get("user_id"):
                return {"error": f"Employee {emp['name']} has no Odoo user."}

            members = [
                {
                    "employee_id": emp["id"],
                    "user_id": emp["user_id"][0],
                    "name": emp["name"],
                    "resource_calendar_id": emp.get("resource_calendar_id"),
                }
            ]
            team_info = {
                "id": emp["department_id"][0] if emp.get("department_id") else None,
                "name": emp["department_id"][1] if emp.get("department_id") else None,
            }
            scope = "person"
            extra: List[int] = []
        else:
            dept, err = _resolve_team(team_id, team_name)
            if err or not dept:
                return {"error": err or "Team not found."}
            key = (team_name or "").strip().lower()
            cfg = TEAM_ALIASES.get(key, {})
            extra = list(extra_user_ids if extra_user_ids is not None else cfg.get("extra_user_ids") or [])
            members = _fetch_members(dept["id"], extra)
            team_info = {"id": dept["id"], "name": dept["name"]}
            scope = "team"

        if not members:
            return {"error": "No team members with Odoo users found."}

        user_ids = [m["user_id"] for m in members]
        team_user_set = set(user_ids)
        planned_map = _planned_hours_per_user(models, uid, user_ids, team_user_set)

        member_rows = []
        for m in members:
            planned = planned_map.get(m["user_id"], 0.0)
            member_rows.append(_build_member_coverage(m, planned, month_specs, ref))

        team_months: List[Dict[str, Any]] = []
        for i, month_key in enumerate(month_keys):
            w_sum = sum(m["months"][i]["workload_hours"] for m in member_rows)
            c_sum = sum(m["months"][i]["capacity_hours"] for m in member_rows)
            if c_sum > 0:
                pct = min(100, round(100 * w_sum / c_sum))
            else:
                pct = 100 if w_sum <= 0 else 0
            team_months.append(
                {
                    "month": month_key,
                    "month_label": _month_label(month_key),
                    "workload_hours": round(w_sum, 1),
                    "capacity_hours": round(c_sum, 1),
                    "coverage_pct": pct,
                }
            )

        total_planned = round(sum(m["planned_hours"] for m in member_rows), 1)
        total_capacity = _sum_capacity(team_months)

        for m in member_rows:
            m["total_capacity_hours"] = _sum_capacity(m.get("months") or [])

        return {
            "as_of": ref.isoformat(),
            "scope": scope,
            "team": team_info,
            "velocity_note": VELOCITY_NOTE,
            "months": month_keys,
            "total_planned_hours": total_planned,
            "total_capacity_hours": total_capacity,
            "team_coverage": team_months,
            "members": member_rows,
        }
    except Exception as e:
        _logger.error("compute_coverage1: %s", e)
        return {"error": str(e)}


def format_coverage1_slack(data: Dict[str, Any]) -> str:
    if data.get("error"):
        if data.get("error") == "usage":
            return data.get("message", "Usage: /coverage1 xfiles | devteam | Name")
        return f":warning: {data['error']}"
    if data.get("ambiguous"):
        lines = [f":warning: {data.get('message', 'Ambiguous')}"]
        for m in data.get("matches") or []:
            lines.append(f"  • {m.get('name', m)}")
        return "\n".join(lines)

    scope = data.get("scope", "team")
    team_name = (data.get("team") or {}).get("name") or "Team"
    lines: List[str] = []

    if scope == "person" and data.get("members"):
        m = data["members"][0]
        lines.append(f"*{m['name']} Coverage 1*")
        lines.append(f"_{data.get('velocity_note', VELOCITY_NOTE)}_")
        lines.append(f"*{_velocity_hpd(m)}* — {m.get('velocity_label', '')}")
        lines.append(f"• {_format_month_coverage_bits(m.get('months') or [])}")
        lines.append(
            f"  ({_format_planned_capacity_summary(m['planned_hours'], m.get('total_capacity_hours', 0))})"
        )
        if m.get("time_off"):
            lines.append(f"  Time off: {', '.join(m['time_off'])}")
        return "\n".join(lines)

    short_team = team_name.replace("Team ", "").split(" - ")[0].strip()
    lines.append(f"*Team {short_team} Coverage 1*")
    lines.append(f"_{data.get('velocity_note', VELOCITY_NOTE)}_")
    lines.append(f"• {_format_month_coverage_bits(data.get('team_coverage') or [])}")
    lines.append(
        f"  ({_format_planned_capacity_summary(data.get('total_planned_hours', 0), data.get('total_capacity_hours', 0))})"
    )
    members = data.get("members") or []
    if members:
        lines.append(f"_{_format_team_velocity_roster(members)}_")
    for m in members:
        mb = _format_month_coverage_bits(m.get("months") or [])
        cap = m.get("total_capacity_hours", 0)
        line = (
            f"  ◦ {m['name']} · {_velocity_hpd(m)}: {mb} "
            f"(planned {m['planned_hours']:.0f} h · avail {cap:.0f} h)"
        )
        if m.get("time_off"):
            line += f" — timeoff: {', '.join(m['time_off'])}"
        lines.append(line)
    return "\n".join(lines)


def get_coverage1(
    team_id: Optional[int] = None,
    team_name: Optional[str] = None,
    person_name: Optional[str] = None,
    employee_id: Optional[int] = None,
    extra_user_ids: Optional[List[int]] = None,
    months: int = 3,
    format: str = "json",
) -> Union[Dict[str, Any], str]:
    data = compute_coverage1(
        team_id=team_id,
        team_name=team_name,
        person_name=person_name,
        employee_id=employee_id,
        extra_user_ids=extra_user_ids,
        months=months,
    )
    if format == "slack":
        return format_coverage1_slack(data)
    return data
