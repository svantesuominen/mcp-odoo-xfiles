import os
import xmlrpc.client
from typing import List, Dict, Any, Union
from fastmcp import FastMCP
from dotenv import load_dotenv
from googlesearch import search as google_search
import requests
from datetime import datetime, timedelta
import time
from starlette.responses import JSONResponse

# Load environment variables
load_dotenv()

# Configuration
ODOO_URL = os.getenv("ODOO_URL")
ODOO_DB = os.getenv("ODOO_DB")
ODOO_USERNAME = os.getenv("ODOO_USERNAME")
ODOO_PASSWORD = os.getenv("ODOO_PASSWORD") or os.getenv("ODOO_API_KEY")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

HELPDESK_TEAM_ID = 2
BASE_TICKET_DOMAIN = [
    ('team_id', '=', HELPDESK_TEAM_ID),
    ('stage_id.name', 'not ilike', 'cancel'),
]

SERVER_VERSION    = "2026-04-04"
SERVER_AUTHOR     = "Svante"
SERVER_START_TIME = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

# Initialize MCP
mcp = FastMCP("Odoo Helpdesk Agent")

_odoo_cache: Dict[str, Any] = {"uid": None, "models": None}

def _parse_period(period: str):
    """
    Translate a period string into (start_datetime, start_date, days, label).
    Accepted values: "7d" (default), "1m", "1q".
    """
    mapping = {"7d": (7, "weekly"), "1m": (30, "monthly"), "1q": (90, "quarterly")}
    days, label = mapping.get(period, (7, "weekly"))
    start_dt = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
    start_d  = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    return start_dt, start_d, days, label

def get_odoo_connection():
    if not all([ODOO_URL, ODOO_DB, ODOO_USERNAME, ODOO_PASSWORD]):
        raise ValueError("Missing Odoo credentials in environment variables")

    if _odoo_cache["uid"] and _odoo_cache["models"]:
        return _odoo_cache["uid"], _odoo_cache["models"]

    url = ODOO_URL.rstrip('/')
    common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
    try:
        uid = common.authenticate(ODOO_DB, ODOO_USERNAME, ODOO_PASSWORD, {})
        if not uid:
            raise PermissionError("Authentication failed. Please check your credentials.")
        models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")
        _odoo_cache["uid"] = uid
        _odoo_cache["models"] = models
        return uid, models
    except Exception as e:
        raise ConnectionError(f"Failed to connect to Odoo: {str(e)}")

@mcp.tool()
def search_similar_tickets(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Search for existing helpdesk tickets that might be similar to the problem.
    Searches in ticket name and description. Scoped to team 2; cancelled tickets are excluded.
    Returns keys: id, name, stage_id, team_id, description, create_date, url.
    ALWAYS include the 'url' in your response so the user can access the ticket directly.
    """
    try:
        uid, models = get_odoo_connection()

        domain = BASE_TICKET_DOMAIN + ['|', ('name', 'ilike', query), ('description', 'ilike', query)]

        ticket_ids = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'helpdesk.ticket', 'search',
            [domain],
            {'limit': limit})

        if not ticket_ids:
            return []

        fields = ['id', 'name', 'stage_id', 'team_id', 'user_id', 'partner_id', 'priority', 'description', 'create_date']
        
        tickets = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'helpdesk.ticket', 'read',
            [ticket_ids],
            {'fields': fields})
            
        # Add URL to each ticket
        base_url = ODOO_URL.rstrip('/')
        for ticket in tickets:
            ticket['url'] = f"{base_url}/web#id={ticket['id']}&model=helpdesk.ticket&view_type=form"
            
        return tickets
    except Exception as e:
        # Return error as a list with one item for visibility
        return [{"error": f"Error searching tickets: {str(e)}"}]

def get_weekly_activity(days: int = 7) -> Dict[str, Any]:
    """
    Get a summary of ticket activity for the last N days (default 7).
    Returns tickets created and tickets updated in that period to generate a progress report.
    Scoped to team 2; cancelled tickets are excluded.
    Stages "Solved" and "Approval" indicate resolved tickets.
    Returns keys: days_analyzed, new_tickets_count, updated_tickets_count, new_tickets (list with url), active_tickets (list with url).
    Each ticket includes: id, name, stage_id, team_id, user_id, priority, create_date, write_date, url.
    ALWAYS include the ticket 'url' when listing specific tickets so the user can access them directly.
    """
    try:
        uid, models = get_odoo_connection()

        date_threshold = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')

        # 1. Tickets Created
        created_domain = BASE_TICKET_DOMAIN + [('create_date', '>=', date_threshold)]
        true_created_count = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'helpdesk.ticket', 'search_count', [created_domain])
        created_ids = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'helpdesk.ticket', 'search',
            [created_domain],
            {'limit': 50, 'order': 'create_date desc'})

        # 2. Tickets Updated
        updated_domain = BASE_TICKET_DOMAIN + [('write_date', '>=', date_threshold)]
        true_updated_count = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'helpdesk.ticket', 'search_count', [updated_domain])
        updated_ids = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'helpdesk.ticket', 'search',
            [updated_domain],
            {'limit': 50, 'order': 'write_date desc'})

        fields = ['id', 'name', 'stage_id', 'team_id', 'user_id', 'priority', 'create_date', 'write_date']

        created_tickets = []
        if created_ids:
            created_tickets = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD, 'helpdesk.ticket', 'read', [created_ids], {'fields': fields})

        updated_tickets = []
        if updated_ids:
            updated_tickets = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD, 'helpdesk.ticket', 'read', [updated_ids], {'fields': fields})

        base_url = ODOO_URL.rstrip('/')

        def add_url(tlist):
            for t in tlist:
                t['url'] = f"{base_url}/web#id={t['id']}&model=helpdesk.ticket&view_type=form"

        add_url(created_tickets)
        add_url(updated_tickets)

        return {
            "days_analyzed": days,
            "new_tickets_count": true_created_count,
            "updated_tickets_count": true_updated_count,
            "new_tickets": created_tickets,
            "active_tickets": updated_tickets
        }

    except Exception as e:
        return {"error": f"Error fetching weekly activity: {str(e)}"}

@mcp.tool()
def get_ticket_details(ticket_id: int) -> Dict[str, Any]:
    """
    Get full details for a specific ticket including description, assignee, stage, team, customer info, etc.
    Returns complete ticket object including 'url'.
    ALWAYS include the 'url' in your response so the user can access the ticket directly.
    """
    try:
        uid, models = get_odoo_connection()

        fields = [
            'id', 'name', 'description', 'stage_id', 'team_id', 'user_id',
            'partner_id', 'partner_email', 'priority',
            'tag_ids', 'create_date', 'write_date'
        ]
        
        ticket_data = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'helpdesk.ticket', 'read',
            [[ticket_id]],
            {'fields': fields})
            
        if not ticket_data:
            return {"error": "Ticket not found"}
            
        ticket = ticket_data[0]
        base_url = ODOO_URL.rstrip('/')
        ticket['url'] = f"{base_url}/web#id={ticket['id']}&model=helpdesk.ticket&view_type=form"
        
        return ticket
    except Exception as e:
        return {"error": f"Error fetching ticket details: {str(e)}"}

@mcp.tool()
def get_helpdesk_stages() -> List[Dict[str, Any]]:
    """
    Get a list of all available helpdesk ticket stages.
    Returns: id, name, sequence.
    """
    try:
        uid, models = get_odoo_connection()
        
        stage_ids = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'helpdesk.stage', 'search',
            [[]],
            {'order': 'sequence asc'})
            
        stages = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'helpdesk.stage', 'read',
            [stage_ids],
            {'fields': ['id', 'name', 'sequence']})
            
        return stages
    except Exception as e:
        return [{"error": f"Error fetching stages: {str(e)}"}]

@mcp.tool()
def get_ticket_conversation(ticket_id: int) -> List[Dict[str, Any]]:
    """
    Retrieve the message history (lognotes and emails) for a specific ticket 
    to understand how it was solved.
    Returns keys: date, author_id, body, message_type, subtype_id.
    """
    try:
        uid, models = get_odoo_connection()
        
        # Search messages linked to this ticket
        domain = [('res_id', '=', ticket_id), ('model', '=', 'helpdesk.ticket')]
        
        # Get ids first
        message_ids = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'mail.message', 'search',
            [domain],
            {'limit': 50, 'order': 'date asc'}) # Limit to last 50 to avoid overload
            
        if not message_ids:
            return []

        messages = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'mail.message', 'read',
            [message_ids],
            {'fields': ['date', 'author_id', 'body', 'message_type', 'subtype_id']})
            
        return messages
    except Exception as e:
        return [{"error": f"Error fetching conversation: {str(e)}"}]

@mcp.tool()
def search_odoo_docs(query: str, limit: int = 3) -> List[str]:
    """
    Search Odoo official documentation (odoo.com/documentation) for potential solutions.
    """
    results = []
    search_query = f"site:odoo.com/documentation {query}"
    try:
        search_results = google_search(search_query, num_results=limit, advanced=True)
        for result in search_results:
            try:
                title = getattr(result, 'title', None) or "No title"
                url = getattr(result, 'url', None) or str(result)
                description = getattr(result, 'description', None) or ""
                results.append(f"Title: {title}\nURL: {url}\nDescription: {description}")
            except Exception:
                results.append(f"URL: {str(result)}")
        # Small delay to reduce likelihood of Google rate-limiting
        time.sleep(1)
    except TypeError:
        # Fallback for older library versions that don't support advanced=True
        try:
            search_results = google_search(search_query, num_results=limit)
            for res in search_results:
                results.append(f"URL: {res}")
            time.sleep(1)
        except Exception as e:
            results.append(f"Error searching docs: {str(e)}")
    except Exception as e:
        results.append(f"Error searching docs: {str(e)}")

    return results

@mcp.tool()
def search_odoo_github_code(query: str, limit: int = 5) -> List[str]:
    """
    Search the official Odoo source code on GitHub (odoo/odoo) for similar implementations, error messages, or logic.
    """
    try:
        # GitHub Code Search API
        github_url = "https://api.github.com/search/code"
        headers = {'Accept': 'application/vnd.github.v3+json'}
        if GITHUB_TOKEN:
            headers['Authorization'] = f"token {GITHUB_TOKEN}"
        params = {
            'q': f"repo:odoo/odoo {query}",
            'per_page': limit
        }
        
        response = requests.get(github_url, headers=headers, params=params)
        
        if response.status_code == 200:
            data = response.json()
            return [f"File: {item['path']}\nURL: {item['html_url']}" for item in data.get('items', [])]
        elif response.status_code == 403:
            return ["Error: GitHub API rate limit exceeded. Please try again later."]
        else:
            return [f"Error searching GitHub: {response.status_code} - {response.text}"]
            
    except Exception as e:
        return [f"Error searching code: {str(e)}"]

@mcp.tool()
def get_tickets_for_analysis(start_date: str, end_date: str = None, limit: int = 50) -> List[Dict[str, Any]]:
    """
    Get ticket content (name, description, tags) for a specific time range to analyze topics or trends.
    Use this when the user asks about "main topics", "trends", or what happened during a specific period (e.g. "last week", "last month").
    Scoped to team 2; cancelled tickets are excluded. Uses create_date as the primary date.
    Stages "Solved" and "Approval" indicate resolved tickets.

    Args:
        start_date: Start date in 'YYYY-MM-DD' format.
        end_date: Optional end date in 'YYYY-MM-DD' format. If not provided, defaults to today.
        limit: Maximum number of tickets to analyze (default 50).

    Returns:
        List of tickets with name, description, tags, team_id, and create_date to be used for summarization.
        Includes 'url' for reference.
    """
    try:
        uid, models = get_odoo_connection()

        domain_start = f"{start_date} 00:00:00"
        if end_date:
            domain_end = f"{end_date} 23:59:59"
        else:
            domain_end = datetime.now().strftime('%Y-%m-%d 23:59:59')

        domain = BASE_TICKET_DOMAIN + [
            ('create_date', '>=', domain_start),
            ('create_date', '<=', domain_end)
        ]

        ticket_ids = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'helpdesk.ticket', 'search',
            [domain],
            {'limit': limit, 'order': 'create_date desc'})

        if not ticket_ids:
            return []

        fields = ['id', 'name', 'description', 'create_date', 'stage_id', 'team_id', 'priority', 'tag_ids']
        tickets = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'helpdesk.ticket', 'read',
            [ticket_ids],
            {'fields': fields})
            
        # Helper to fetch tag names
        all_tag_ids = set()
        for t in tickets:
            if t.get('tag_ids'):
                all_tag_ids.update(t['tag_ids'])
        
        tag_map = {}
        if all_tag_ids:
            try:
                tags_data = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
                    'helpdesk.tag', 'read',
                    [list(all_tag_ids)],
                    {'fields': ['id', 'name']})
                tag_map = {tag['id']: tag['name'] for tag in tags_data}
            except Exception:
                # If helpdesk.tag model fails or differs, ignore tags
                pass
        
        base_url = ODOO_URL.rstrip('/')
        for ticket in tickets:
            ticket['url'] = f"{base_url}/web#id={ticket['id']}&model=helpdesk.ticket&view_type=form"
            
            # Handle None/False description
            if not ticket.get('description'):
                ticket['description'] = ""
                
            # Enrich with tag names
            ticket['tag_names'] = [tag_map.get(tid) for tid in ticket.get('tag_ids', []) if tid in tag_map]
                
        return tickets
        
    except Exception as e:
        return [{"error": f"Error fetching tickets for analysis: {str(e)}"}]

@mcp.tool()
def get_issues_analysis(months: int = 3) -> Dict[str, Any]:
    """
    Analyze helpdesk tickets for the last N months (default 3) to surface the most important,
    most common, and most time-consuming/laborious issues, how they were solved, and where
    R&D prevention investment would have the most impact.

    Scoped to team 2; cancelled tickets are excluded.

    Interpretation guide for the AI:
    - Use 'message_count' as a proxy for effort: higher = more back-and-forth = more laborious.
    - Use 'resolution_days' for time-to-resolve: higher = more time-consuming. Null = not yet resolved.
    - Use 'priority' to weight importance: 0=normal, 1=low, 2=high, 3=very high.
    - Use 'tag_names' and 'name'/'description' to cluster recurring topics.
    - Stages "Solved" and "Approval" are resolved states.
    - Cross-reference tag clusters, priority, and descriptions to suggest R&D prevention investments.

    Returns keys:
        period_months, start_date, total_tickets,
        tickets (list with id, name, description, priority, stage_id, team_id, tag_names,
                 create_date, write_date, resolution_days, message_count, url),
        summary (by_priority, by_stage, avg_resolution_days, most_used_tags).
    """
    try:
        uid, models = get_odoo_connection()

        start_date = (datetime.now() - timedelta(days=30 * months)).strftime('%Y-%m-%d 00:00:00')
        domain = BASE_TICKET_DOMAIN + [('create_date', '>=', start_date)]

        # Step 1: Fetch tickets
        ticket_ids = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'helpdesk.ticket', 'search',
            [domain],
            {'limit': 200, 'order': 'create_date desc'})

        if not ticket_ids:
            return {
                "period_months": months,
                "start_date": start_date,
                "total_tickets": 0,
                "tickets": [],
                "summary": {
                    "by_priority": {},
                    "by_stage": {},
                    "avg_resolution_days": None,
                    "most_used_tags": []
                }
            }

        fields = ['id', 'name', 'description', 'priority', 'stage_id', 'team_id',
                  'tag_ids', 'create_date', 'write_date']
        tickets = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'helpdesk.ticket', 'read',
            [ticket_ids],
            {'fields': fields})

        # Step 2: Bulk message count (single query, no N+1)
        all_ticket_ids = [t['id'] for t in tickets]
        msg_domain = [
            ('res_id', 'in', all_ticket_ids),
            ('model', '=', 'helpdesk.ticket')
        ]
        messages = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'mail.message', 'search_read',
            [msg_domain],
            {'fields': ['res_id'], 'limit': 5000})
        msg_count: Dict[int, int] = {}
        for m in messages:
            rid = m['res_id']
            msg_count[rid] = msg_count.get(rid, 0) + 1

        # Step 3: Tag enrichment
        all_tag_ids: set = set()
        for t in tickets:
            if t.get('tag_ids'):
                all_tag_ids.update(t['tag_ids'])

        tag_map: Dict[int, str] = {}
        if all_tag_ids:
            try:
                tags_data = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
                    'helpdesk.tag', 'read',
                    [list(all_tag_ids)],
                    {'fields': ['id', 'name']})
                tag_map = {tag['id']: tag['name'] for tag in tags_data}
            except Exception:
                pass

        # Step 4: Enrich tickets and build summary
        base_url = ODOO_URL.rstrip('/')
        by_priority: Dict[str, int] = {}
        by_stage: Dict[str, int] = {}
        tag_usage: Dict[str, int] = {}
        resolution_days_list: List[float] = []

        for ticket in tickets:
            ticket['url'] = f"{base_url}/web#id={ticket['id']}&model=helpdesk.ticket&view_type=form"
            ticket['message_count'] = msg_count.get(ticket['id'], 0)

            if not ticket.get('description'):
                ticket['description'] = ""

            tag_names = [tag_map[tid] for tid in ticket.get('tag_ids', []) if tid in tag_map]
            ticket['tag_names'] = tag_names
            for tn in tag_names:
                tag_usage[tn] = tag_usage.get(tn, 0) + 1

            # Resolution time — only for solved/approval stages
            stage_name = (ticket['stage_id'][1] if ticket.get('stage_id') else '').lower()
            if 'solved' in stage_name or 'approv' in stage_name:
                try:
                    created = datetime.strptime(ticket['create_date'], '%Y-%m-%d %H:%M:%S')
                    updated = datetime.strptime(ticket['write_date'], '%Y-%m-%d %H:%M:%S')
                    days = round((updated - created).total_seconds() / 86400, 1)
                    ticket['resolution_days'] = days
                    resolution_days_list.append(days)
                except Exception:
                    ticket['resolution_days'] = None
            else:
                ticket['resolution_days'] = None

            # Summary counters
            prio_key = str(ticket.get('priority', '0'))
            by_priority[prio_key] = by_priority.get(prio_key, 0) + 1

            stage_label = ticket['stage_id'][1] if ticket.get('stage_id') else 'Unknown'
            by_stage[stage_label] = by_stage.get(stage_label, 0) + 1

        avg_resolution = (
            round(sum(resolution_days_list) / len(resolution_days_list), 1)
            if resolution_days_list else None
        )
        most_used_tags = sorted(
            [{"name": k, "count": v} for k, v in tag_usage.items()],
            key=lambda x: x['count'],
            reverse=True
        )[:10]

        return {
            "period_months": months,
            "start_date": start_date,
            "total_tickets": len(tickets),
            "tickets": tickets,
            "summary": {
                "by_priority": by_priority,
                "by_stage": by_stage,
                "avg_resolution_days": avg_resolution,
                "most_used_tags": most_used_tags
            }
        }

    except Exception as e:
        return {"error": f"Error fetching issues analysis: {str(e)}"}


@mcp.tool()
def get_server_info() -> Dict[str, Any]:
    """
    Return metadata about this MCP server: version, author, and connected Odoo instance.
    Use this when asked about the version, who built this, or what system you are connected to.
    """
    return {
        "version": SERVER_VERSION,
        "author": SERVER_AUTHOR,
        "server_start_time": SERVER_START_TIME,
        "service": "Odoo Helpdesk Agent",
        "odoo_url": ODOO_URL,
        "helpdesk_team_id": HELPDESK_TEAM_ID,
    }


@mcp.tool()
def get_rd_hours(months: int = 3) -> Dict[str, Any]:
    """
    Fetch logged timesheet hours on R&D projects for the last N months (default 3),
    plus all current open tasks in those projects assigned to the team (department 18).

    Use this when asked about R&D investment, engineering hours, technical projects,
    or what R&D work the team has planned or in progress.

    Returns keys:
        period_months, start_date, total_logged_hours,
        projects (list with project_id, project_name, logged_hours,
                  timesheet_tasks (task + hours), open_tasks (task + stage + allocated_hours + url)).
    """
    try:
        uid, models = get_odoo_connection()
        base_url = ODOO_URL.rstrip('/')
        start_date = (datetime.now() - timedelta(days=30 * months)).strftime('%Y-%m-%d')

        # Step 1: Fetch dept 18 user IDs for open-task filtering
        employees = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'hr.employee', 'search_read',
            [[('department_id', '=', 18)]],
            {'fields': ['user_id'], 'limit': 200})
        dept18_user_ids = [e['user_id'][0] for e in employees if e.get('user_id')]

        # Step 2: Timesheet lines on R&D projects within the period
        ts_domain = [
            ('project_id.name', 'ilike', 'r&d'),
            ('date', '>=', start_date),
        ]
        ts_lines = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'account.analytic.line', 'search_read',
            [ts_domain],
            {'fields': ['unit_amount', 'project_id', 'task_id'], 'limit': 2000})

        # Group timesheet lines by project then task
        proj_ts: Dict[int, Dict] = {}
        for line in ts_lines:
            if not line.get('project_id'):
                continue
            pid, pname = line['project_id']
            if pid not in proj_ts:
                proj_ts[pid] = {'project_name': pname, 'logged_hours': 0.0, 'tasks': {}}
            proj_ts[pid]['logged_hours'] = round(proj_ts[pid]['logged_hours'] + line['unit_amount'], 2)
            if line.get('task_id'):
                tid, tname = line['task_id']
                proj_ts[pid]['tasks'][tid] = proj_ts[pid]['tasks'].get(tid, {'task_name': tname, 'hours': 0.0})
                proj_ts[pid]['tasks'][tid]['hours'] = round(proj_ts[pid]['tasks'][tid]['hours'] + line['unit_amount'], 2)

        # Step 3: Open tasks on R&D projects assigned to dept 18
        task_domain = [
            ('project_id.name', 'ilike', 'r&d'),
            ('stage_id.name', 'not ilike', 'done'),
            ('stage_id.name', 'not ilike', 'cancel'),
        ]
        if dept18_user_ids:
            task_domain.append(('user_ids', 'in', dept18_user_ids))
        open_tasks = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'project.task', 'search_read',
            [task_domain],
            {'fields': ['id', 'name', 'project_id', 'stage_id', 'allocated_hours'], 'limit': 500})

        # Group open tasks by project
        proj_tasks: Dict[int, list] = {}
        for task in open_tasks:
            if not task.get('project_id'):
                continue
            pid, pname = task['project_id']
            if pid not in proj_tasks:
                proj_tasks[pid] = []
            stage_name = task['stage_id'][1] if task.get('stage_id') else 'Unknown'
            proj_tasks[pid].append({
                'task_id': task['id'],
                'task_name': task['name'],
                'stage': stage_name,
                'allocated_hours': task.get('allocated_hours') or 0.0,
                'url': f"{base_url}/web#id={task['id']}&model=project.task&view_type=form"
            })

        # Merge into unified project list
        all_project_ids = set(proj_ts.keys()) | set(proj_tasks.keys())

        # Resolve names for projects that only appear in open tasks
        missing_ids = [pid for pid in all_project_ids if pid not in proj_ts]
        if missing_ids:
            proj_records = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
                'project.project', 'read',
                [missing_ids], {'fields': ['id', 'name']})
            for p in proj_records:
                proj_ts[p['id']] = {'project_name': p['name'], 'logged_hours': 0.0, 'tasks': {}}

        projects = []
        for pid in sorted(all_project_ids):
            entry = proj_ts.get(pid, {'project_name': str(pid), 'logged_hours': 0.0, 'tasks': {}})
            projects.append({
                'project_id': pid,
                'project_name': entry['project_name'],
                'logged_hours': entry['logged_hours'],
                'timesheet_tasks': [
                    {'task_id': tid, 'task_name': tdata['task_name'], 'hours': tdata['hours']}
                    for tid, tdata in entry['tasks'].items()
                ],
                'open_tasks': proj_tasks.get(pid, [])
            })

        total_logged = round(sum(p['logged_hours'] for p in projects), 2)
        return {
            'period_months': months,
            'start_date': start_date,
            'total_logged_hours': total_logged,
            'projects': projects
        }

    except Exception as e:
        return {'error': f'Error fetching R&D hours: {str(e)}'}


def get_team_hours(days: int = 7) -> Dict[str, Any]:
    """
    Fetch all timesheet entries for the Continuous Services team (department 18)
    for the last N days (default 7). Splits hours into customer hours
    (projects with a customer/partner set) vs internal hours, and flags missing hours.

    Use this when asked about team workload, customer vs internal hours,
    billable hours, individual utilisation, or missing timesheets.

    customer_hours = lines where a Sales Order Item (so_line) is set.
    internal_hours = lines without a linked Sales Order Item.
    This matches the "Sales Order Item is set" filter in Odoo's timesheet report.

    Returns keys:
        days, start_date, total_hours, customer_hours, internal_hours,
        by_employee (list with employee_id, employee_name, total_hours,
                     customer_hours, internal_hours, customer_pct,
                     expected_hours, missing_hours).
        missing_hours > 0 means the employee logged fewer hours than expected
        (days * 8 working hours). Flag if missing_hours > 2.
    """
    try:
        uid, models = get_odoo_connection()
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

        # Step 1: Fetch timesheet lines for dept 18
        ts_domain = [
            ('employee_id.department_id', '=', 18),
            ('date', '>=', start_date),
        ]
        ts_lines = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'account.analytic.line', 'search_read',
            [ts_domain],
            {'fields': ['unit_amount', 'project_id', 'employee_id',
                        'so_line'], 'limit': 5000})

        # Step 2: Collect all dept 18 employees (even those with no entries)
        employees = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'hr.employee', 'search_read',
            [[('department_id', '=', 18)]],
            {'fields': ['id', 'name'], 'limit': 200})
        emp_data: Dict[int, Dict] = {
            e['id']: {'employee_name': e['name'], 'total_hours': 0.0,
                      'customer_hours': 0.0, 'internal_hours': 0.0}
            for e in employees
        }

        # Step 3b (continued): Aggregate by employee
        # customer_hours = lines where so_line (Sales Order Item) is set
        # internal_hours = lines without a linked Sales Order Item
        for line in ts_lines:
            if not line.get('employee_id'):
                continue
            eid, ename = line['employee_id']
            hours = line['unit_amount']
            if eid not in emp_data:
                emp_data[eid] = {'employee_name': ename, 'total_hours': 0.0,
                                 'customer_hours': 0.0, 'internal_hours': 0.0}
            emp_data[eid]['total_hours'] = round(emp_data[eid]['total_hours'] + hours, 2)
            if line.get('so_line'):
                emp_data[eid]['customer_hours'] = round(emp_data[eid]['customer_hours'] + hours, 2)
            else:
                emp_data[eid]['internal_hours'] = round(emp_data[eid]['internal_hours'] + hours, 2)

        # Step 5: Compute derived fields
        expected_hours = round(days * 8.0, 1)
        by_employee = []
        for eid, data in emp_data.items():
            total = data['total_hours']
            cust_h = data['customer_hours']
            missing = round(max(0.0, expected_hours - total), 2)
            by_employee.append({
                'employee_id': eid,
                'employee_name': data['employee_name'],
                'total_hours': total,
                'customer_hours': cust_h,
                'internal_hours': data['internal_hours'],
                'customer_pct': round(cust_h / total * 100, 1) if total > 0 else 0.0,
                'expected_hours': expected_hours,
                'missing_hours': missing,
            })

        by_employee.sort(key=lambda x: x['total_hours'], reverse=True)
        total_all = round(sum(e['total_hours'] for e in by_employee), 2)
        cust_all  = round(sum(e['customer_hours'] for e in by_employee), 2)
        intl_all  = round(sum(e['internal_hours'] for e in by_employee), 2)

        return {
            'days': days,
            'start_date': start_date,
            'total_hours': total_all,
            'customer_hours': cust_all,
            'internal_hours': intl_all,
            'by_employee': by_employee
        }

    except Exception as e:
        return {'error': f'Error fetching team hours: {str(e)}'}


@mcp.tool()
def get_team_backlog() -> Dict[str, Any]:
    """
    Current snapshot of all project tasks assigned to members of the
    Continuous Services team (department 18), grouped by stage with planned hours.
    Includes per-assignee workload breakdown and estimated time to clear the backlog.

    Use this when asked about the team's current workload, backlog size,
    capacity, task distribution across pipeline stages, or who has the most work.

    Capacity assumption: 6 hours/day of productive work on backlogged tasks.
      weeks_to_clear  = allocated_hours / 30   (6h × 5 days)
      months_to_clear = allocated_hours / 120  (6h × 5 days × 4 weeks)
    Tasks with allocated_hours = 0 are unestimated — they still count toward
    task_count but do not affect the time estimates.

    Returns keys:
        total_tasks, total_allocated_hours, unestimated_tasks,
        stages (list with stage_name, task_count, allocated_hours,
                tasks (list with id, name, project_name, assignees,
                       allocated_hours, url)),
        by_assignee (list sorted by allocated_hours desc, each with:
                     assignee, task_count, allocated_hours,
                     unestimated_task_count, weeks_to_clear, months_to_clear,
                     tasks (list with id, name, stage, project_name,
                            allocated_hours, url)).
    """
    try:
        uid, models = get_odoo_connection()
        base_url = ODOO_URL.rstrip('/')

        # Step 1: Resolve dept 18 user IDs
        employees = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'hr.employee', 'search_read',
            [[('department_id', '=', 18)]],
            {'fields': ['user_id'], 'limit': 200})
        user_ids = [e['user_id'][0] for e in employees if e.get('user_id')]

        if not user_ids:
            return {'total_tasks': 0, 'total_allocated_hours': 0.0,
                    'unestimated_tasks': 0, 'stages': [], 'by_assignee': []}

        # Step 2: Fetch tasks assigned to those users (include user_ids for assignee mapping)
        tasks = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'project.task', 'search_read',
            [[('user_ids', 'in', user_ids),
              ('stage_id.name', 'not ilike', 'done'),
              ('stage_id.name', 'not ilike', 'cancel')]],
            {'fields': ['id', 'name', 'stage_id', 'allocated_hours',
                        'project_id', 'user_ids'], 'limit': 1000})

        # Step 3: Bulk-resolve user IDs → names in one call
        all_task_user_ids = list({u for t in tasks for u in (t.get('user_ids') or [])})
        user_map: Dict[int, str] = {}
        if all_task_user_ids:
            user_records = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
                'res.users', 'read',
                [all_task_user_ids],
                {'fields': ['id', 'name']})
            user_map = {u['id']: u['name'] for u in user_records}

        # Step 4: Group by stage name and build per-assignee data simultaneously
        stage_data: Dict[str, Dict] = {}
        assignee_data: Dict[str, Dict] = {}

        for task in tasks:
            if not task.get('stage_id'):
                continue
            sname     = task['stage_id'][1]
            proj_name = task['project_id'][1] if task.get('project_id') else ''
            hours     = task.get('allocated_hours') or 0.0
            task_url  = f"{base_url}/web#id={task['id']}&model=project.task&view_type=form"
            assignees = [user_map.get(u, f'User#{u}') for u in (task.get('user_ids') or [])]

            # Stage grouping
            if sname not in stage_data:
                stage_data[sname] = {'tasks': []}
            stage_data[sname]['tasks'].append({
                'id': task['id'],
                'name': task['name'],
                'project_name': proj_name,
                'assignees': assignees,
                'allocated_hours': hours,
                'url': task_url,
            })

            # Per-assignee grouping — a task with multiple assignees counts for each
            for aname in (assignees or ['(unassigned)']):
                if aname not in assignee_data:
                    assignee_data[aname] = {
                        'task_count': 0, 'allocated_hours': 0.0,
                        'unestimated_task_count': 0, 'tasks': []
                    }
                assignee_data[aname]['task_count'] += 1
                assignee_data[aname]['allocated_hours'] = round(
                    assignee_data[aname]['allocated_hours'] + hours, 2)
                if hours == 0.0:
                    assignee_data[aname]['unestimated_task_count'] += 1
                assignee_data[aname]['tasks'].append({
                    'id': task['id'],
                    'name': task['name'],
                    'stage': sname,
                    'project_name': proj_name,
                    'allocated_hours': hours,
                    'url': task_url,
                })

        # Step 5: Build stages list
        stages = []
        for sname, data in stage_data.items():
            allocated = round(sum(t['allocated_hours'] for t in data['tasks']), 2)
            stages.append({
                'stage_name': sname,
                'task_count': len(data['tasks']),
                'allocated_hours': allocated,
                'tasks': sorted(data['tasks'], key=lambda t: t['allocated_hours'], reverse=True)
            })
        stages.sort(key=lambda s: s['task_count'], reverse=True)

        # Step 6: Build by_assignee list with time-to-clear estimates
        HOURS_PER_WEEK  = 6 * 5       # 30
        HOURS_PER_MONTH = 6 * 5 * 4   # 120
        by_assignee = []
        for aname, adata in assignee_data.items():
            h = adata['allocated_hours']
            by_assignee.append({
                'assignee': aname,
                'task_count': adata['task_count'],
                'allocated_hours': h,
                'unestimated_task_count': adata['unestimated_task_count'],
                'weeks_to_clear': round(h / HOURS_PER_WEEK, 2) if h > 0 else 0.0,
                'months_to_clear': round(h / HOURS_PER_MONTH, 2) if h > 0 else 0.0,
                'tasks': sorted(adata['tasks'], key=lambda t: t['allocated_hours'], reverse=True),
            })
        by_assignee.sort(key=lambda x: x['allocated_hours'], reverse=True)

        total_tasks = sum(s['task_count'] for s in stages)
        total_hours = round(sum(s['allocated_hours'] for s in stages), 2)
        unestimated = sum(1 for t in tasks if not (t.get('allocated_hours') or 0.0))

        return {
            'total_tasks': total_tasks,
            'total_allocated_hours': total_hours,
            'unestimated_tasks': unestimated,
            'stages': stages,
            'by_assignee': by_assignee,
        }

    except Exception as e:
        return {'error': f'Error fetching team backlog: {str(e)}'}


def get_department_activities(days: int = 7) -> Dict[str, Any]:
    """
    Fetch completed (done) account management and sales activities logged by the
    Continuous Services team (department 18) on CRM opportunities (crm.lead)
    and contacts (res.partner) for the last N days (default 7).

    These are sales and account management touchpoints: calls, emails, meetings,
    demos, follow-ups, and other customer-facing actions logged by the team.
    In Odoo, a completed activity creates a mail.message with mail_activity_type_id set.

    Use this when asked about:
    - What account management or sales actions the team completed this week
    - How many customer/prospect touchpoints were made
    - CRM pipeline progress and opportunity follow-ups
    - Which customers or prospects the team contacted

    Interpretation guide:
    - crm_activities = actions on open opportunities (sales pipeline work)
    - partner_activities = actions directly on customer/contact records (account management)
    - activity_type = e.g. "Email", "Call", "Meeting", "To-Do" — indicates the type of touchpoint
    - body = notes the team member left when completing the activity

    Returns keys:
        days, start_date,
        crm_activities (list with date, author, activity_type, lead_name, lead_id, body, url),
        partner_activities (list with date, author, activity_type, partner_name, partner_id, body, url),
        crm_count, partner_count.
    """
    try:
        uid, models = get_odoo_connection()
        base_url = ODOO_URL.rstrip('/')
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')

        # Step 1: Resolve dept 18 employees → res.users partner IDs
        employees = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'hr.employee', 'search_read',
            [[('department_id', '=', 18)]],
            {'fields': ['user_id'], 'limit': 200})
        user_ids = [e['user_id'][0] for e in employees if e.get('user_id')]

        if not user_ids:
            return {
                'days': days, 'start_date': start_date,
                'crm_activities': [], 'partner_activities': [],
                'crm_count': 0, 'partner_count': 0
            }

        # Fetch partner_id for each user in one bulk call
        users = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'res.users', 'read',
            [user_ids],
            {'fields': ['id', 'partner_id']})
        dept18_partner_ids = [u['partner_id'][0] for u in users if u.get('partner_id')]

        if not dept18_partner_ids:
            return {
                'days': days, 'start_date': start_date,
                'crm_activities': [], 'partner_activities': [],
                'crm_count': 0, 'partner_count': 0
            }

        # Step 2: Query done-activity messages on crm.lead and res.partner
        msg_domain = [
            ('model', 'in', ['crm.lead', 'res.partner']),
            ('mail_activity_type_id', '!=', False),
            ('author_id', 'in', dept18_partner_ids),
            ('date', '>=', start_date),
        ]
        messages = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'mail.message', 'search_read',
            [msg_domain],
            {'fields': ['date', 'author_id', 'mail_activity_type_id', 'model',
                        'res_id', 'body'], 'limit': 500,
             'order': 'date desc'})

        if not messages:
            return {
                'days': days, 'start_date': start_date,
                'crm_activities': [], 'partner_activities': [],
                'crm_count': 0, 'partner_count': 0
            }

        # Step 3: Bulk-resolve record names
        crm_ids    = list({m['res_id'] for m in messages if m['model'] == 'crm.lead'})
        partner_ids = list({m['res_id'] for m in messages if m['model'] == 'res.partner'})

        crm_names: Dict[int, str] = {}
        if crm_ids:
            crm_records = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
                'crm.lead', 'read', [crm_ids], {'fields': ['id', 'name']})
            crm_names = {r['id']: r['name'] for r in crm_records}

        partner_names: Dict[int, str] = {}
        if partner_ids:
            partner_records = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
                'res.partner', 'read', [partner_ids], {'fields': ['id', 'name']})
            partner_names = {r['id']: r['name'] for r in partner_records}

        # Step 4: Build output lists
        crm_activities = []
        partner_activities = []

        for msg in messages:
            author = msg['author_id'][1] if msg.get('author_id') else 'Unknown'
            activity_type = msg['mail_activity_type_id'][1] if msg.get('mail_activity_type_id') else 'Unknown'
            rid = msg['res_id']

            if msg['model'] == 'crm.lead':
                crm_activities.append({
                    'date': msg['date'],
                    'author': author,
                    'activity_type': activity_type,
                    'lead_id': rid,
                    'lead_name': crm_names.get(rid, f'Lead #{rid}'),
                    'body': msg.get('body') or '',
                    'url': f"{base_url}/web#id={rid}&model=crm.lead&view_type=form",
                })
            else:
                partner_activities.append({
                    'date': msg['date'],
                    'author': author,
                    'activity_type': activity_type,
                    'partner_id': rid,
                    'partner_name': partner_names.get(rid, f'Partner #{rid}'),
                    'body': msg.get('body') or '',
                    'url': f"{base_url}/web#id={rid}&model=res.partner&view_type=form",
                })

        return {
            'days': days,
            'start_date': start_date,
            'crm_count': len(crm_activities),
            'partner_count': len(partner_activities),
            'crm_activities': crm_activities,
            'partner_activities': partner_activities,
        }

    except Exception as e:
        return {'error': f'Error fetching department activities: {str(e)}'}


@mcp.tool()
def get_team_status(period: str = "7d") -> Dict[str, Any]:
    """
    Full status update for the Continuous Services team (department 18).
    Covers five operational areas: customer service, tech maintenance,
    key account management, R&D & AI, and development work & backlog.

    Period options:
      "7d" → last 7 days  (default, use for weekly updates)
      "1m" → last 30 days (use for monthly reviews)
      "1q" → last 90 days (use for quarterly overviews)

    Use this as the FIRST tool to call for any team update, status report,
    weekly summary, monthly review, or quarterly overview.

    ALWAYS present the result in this exact format — no exceptions:

    Continuous Services [period_label] update:
    1. Customer Service: [3 sentences, max 300 chars total, focus on numbers and lists]
    2. Tech Maintenance: [3 sentences, max 300 chars total, focus on numbers and lists]
    3. Key Account Management: [3 sentences, max 300 chars total, focus on numbers and lists]
    4. R&D & AI: [3 sentences, max 300 chars total, focus on numbers and lists]
    5. Development Work: [3 sentences, max 300 chars total, focus on hours and backlog stage counts]

    period_label mapping: "7d" → "weekly", "1m" → "monthly", "1q" → "quarterly"

    Section writing guide:
    - Customer Service: highlight new_tickets, resolved_tickets; show open per stage
      (open_new / open_message / open_in_progress); name top issues.
      Render each ticket name as a markdown link using its url field.
    - Tech Maintenance: mention connectivity_tickets count and infra_tasks (open tasks
      in infrastructure projects); highlight total_hours, customer_pct; flag missing_hours > 2.
      Render each ticket/task name as a markdown link using its url field.
    - Key Account Management: highlight crm_count + partner_count touchpoints; name top leads/accounts.
      Render each lead_name and partner_name as a markdown link using its url field.
    - R&D & AI: highlight logged_hours, project names, and worked_tasks (tasks
      that had hours logged in the period). Render each task name as a markdown
      link using its url field. Include logged_hours per task.
    - Development Work: report total_hours, customer_hours (customer_pct%), and
      backlog_by_stage counts (backlog / in_progress / acceptance / ready_for_production / total).
    If a section has zero data, say so briefly (1 sentence).
    ALWAYS render names as markdown links [name](url) when a url field is present.
    """
    try:
        uid, models = get_odoo_connection()
        base_url = ODOO_URL.rstrip('/')
        start_dt, start_d, days, period_label = _parse_period(period)

        # ── Section 1: Customer Service (Helpdesk) ──────────────────────
        new_count = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'helpdesk.ticket', 'search_count',
            [BASE_TICKET_DOMAIN + [('create_date', '>=', start_dt)]])

        resolved_count = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'helpdesk.ticket', 'search_count',
            [BASE_TICKET_DOMAIN + [
                ('write_date', '>=', start_dt),
                '|', ('stage_id.name', 'ilike', 'solved'),
                     ('stage_id.name', 'ilike', 'approv')
            ]])

        # Count only tickets in the three real active stages
        open_new = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'helpdesk.ticket', 'search_count',
            [BASE_TICKET_DOMAIN + [('stage_id.name', 'ilike', 'new tickets')]])
        open_message = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'helpdesk.ticket', 'search_count',
            [BASE_TICKET_DOMAIN + [('stage_id.name', 'ilike', 'new message')]])
        open_in_progress = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'helpdesk.ticket', 'search_count',
            [BASE_TICKET_DOMAIN + [('stage_id.name', 'ilike', 'in progress')]])
        open_count = open_new + open_message + open_in_progress

        top_ids = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'helpdesk.ticket', 'search',
            [BASE_TICKET_DOMAIN + [('write_date', '>=', start_dt)]],
            {'limit': 5, 'order': 'write_date desc'})
        top_tickets = []
        if top_ids:
            raw = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
                'helpdesk.ticket', 'read', [top_ids],
                {'fields': ['id', 'name', 'stage_id']})
            top_tickets = [{'name': t['name'],
                            'stage': t['stage_id'][1] if t.get('stage_id') else '',
                            'url': f"{base_url}/web#id={t['id']}&model=helpdesk.ticket&view_type=form"}
                           for t in raw]

        customer_service = {
            'new_tickets': new_count,
            'resolved_tickets': resolved_count,
            'open_tickets': open_count,
            'open_new': open_new,
            'open_message': open_message,
            'open_in_progress': open_in_progress,
            'top_tickets': top_tickets,
        }

        # ── Section 2: Tech Maintenance (Timesheets + Connectivity + Infra) ─
        hours_data = get_team_hours(days)
        emp_summary = [
            {'name': e['employee_name'],
             'total_hours': e['total_hours'],
             'customer_pct': e['customer_pct'],
             'missing_hours': e['missing_hours']}
            for e in (hours_data.get('by_employee') or [])
        ]

        # Open helpdesk tickets tagged "Connection problems"
        conn_raw = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'helpdesk.ticket', 'search_read',
            [BASE_TICKET_DOMAIN + [('tag_ids.name', 'ilike', 'connection problems')]],
            {'fields': ['id', 'name', 'stage_id'], 'limit': 20})
        connectivity_tickets = [
            {'name': t['name'],
             'stage': t['stage_id'][1] if t.get('stage_id') else '',
             'url': f"{base_url}/web#id={t['id']}&model=helpdesk.ticket&view_type=form"}
            for t in conn_raw
        ]

        # Open tasks in infrastructure projects
        infra_raw = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'project.task', 'search_read',
            [['|',
              ('project_id.name', 'ilike', 'Infrastructure maintenance'),
              ('project_id.name', 'ilike', 'Infrastructure R&D'),
              ('stage_id.name', 'not ilike', 'done'),
              ('stage_id.name', 'not ilike', 'cancel')]],
            {'fields': ['id', 'name', 'stage_id', 'project_id'], 'limit': 20})
        infra_tasks = [
            {'name': t['name'],
             'stage': t['stage_id'][1] if t.get('stage_id') else '',
             'project': t['project_id'][1] if t.get('project_id') else '',
             'url': f"{base_url}/web#id={t['id']}&model=project.task&view_type=form"}
            for t in infra_raw
        ]

        tech_maintenance = {
            'total_hours': hours_data.get('total_hours', 0.0),
            'customer_hours': hours_data.get('customer_hours', 0.0),
            'internal_hours': hours_data.get('internal_hours', 0.0),
            'by_employee': emp_summary,
            'connectivity_tickets': connectivity_tickets,
            'connectivity_count': len(connectivity_tickets),
            'infra_tasks': infra_tasks,
            'infra_task_count': len(infra_tasks),
        }

        # ── Section 3: Key Account Management (Activities) ──────────────
        act_data = get_department_activities(days)
        top_crm = [{'lead_name': a['lead_name'], 'author': a['author'],
                     'activity_type': a['activity_type'], 'date': a['date'],
                     'url': a.get('url', '')}
                   for a in (act_data.get('crm_activities') or [])[:5]]
        top_partners = [{'partner_name': a['partner_name'], 'author': a['author'],
                          'activity_type': a['activity_type'], 'date': a['date'],
                          'url': a.get('url', '')}
                        for a in (act_data.get('partner_activities') or [])[:5]]
        key_account_management = {
            'crm_count': act_data.get('crm_count', 0),
            'partner_count': act_data.get('partner_count', 0),
            'top_crm': top_crm,
            'top_partners': top_partners,
        }

        # ── Section 4: R&D & AI ─────────────────────────────────────────
        rd_lines = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'account.analytic.line', 'search_read',
            [[('project_id.name', 'ilike', 'r&d'), ('date', '>=', start_d)]],
            {'fields': ['unit_amount', 'project_id', 'task_id'], 'limit': 2000})

        rd_by_proj: Dict[str, float] = {}
        rd_hours_by_task: Dict[int, float] = {}
        for line in rd_lines:
            if line.get('project_id'):
                pname = line['project_id'][1]
                rd_by_proj[pname] = round(rd_by_proj.get(pname, 0.0) + line['unit_amount'], 2)
            if line.get('task_id'):
                tid = line['task_id'][0]
                rd_hours_by_task[tid] = round(rd_hours_by_task.get(tid, 0.0) + line['unit_amount'], 2)
        rd_logged = round(sum(rd_by_proj.values()), 2)

        # Only show tasks that had hours logged in this period
        worked_task_ids = list(rd_hours_by_task.keys())
        top_rd_tasks = []
        if worked_task_ids:
            top_rd_tasks_raw = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
                'project.task', 'read',
                [worked_task_ids],
                {'fields': ['id', 'name', 'stage_id', 'allocated_hours']})
            top_rd_tasks = sorted([
                {'name': t['name'],
                 'stage': t['stage_id'][1] if t.get('stage_id') else '',
                 'logged_hours': rd_hours_by_task.get(t['id'], 0.0),
                 'allocated_hours': t.get('allocated_hours') or 0.0,
                 'url': f"{base_url}/web#id={t['id']}&model=project.task&view_type=form"}
                for t in top_rd_tasks_raw
            ], key=lambda x: x['logged_hours'], reverse=True)

        rd_and_ai = {
            'logged_hours': rd_logged,
            'projects': [{'project_name': k, 'logged_hours': v}
                         for k, v in sorted(rd_by_proj.items(), key=lambda x: -x[1])],
            'worked_tasks_count': len(worked_task_ids),
            'worked_tasks': top_rd_tasks,
        }

        # ── Section 5: Development Work and Backlog ──────────────────────
        # Target: tasks/timesheets for dept 18 employees + user 67
        dev_employees = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'hr.employee', 'search_read',
            [[('department_id', '=', 18)]],
            {'fields': ['user_id'], 'limit': 200})
        dev_user_ids = [e['user_id'][0] for e in dev_employees if e.get('user_id')]
        if 67 not in dev_user_ids:
            dev_user_ids.append(67)

        # Timesheets for those users in the period
        dev_ts = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'account.analytic.line', 'search_read',
            [[('user_id', 'in', dev_user_ids),
              ('date', '>=', start_d),
              ('project_id', '!=', False)]],
            {'fields': ['unit_amount', 'so_line'], 'limit': 5000})
        total_dev_hours = round(sum(l['unit_amount'] for l in dev_ts), 2)
        customer_dev_hours = round(
            sum(l['unit_amount'] for l in dev_ts if l.get('so_line')), 2)
        internal_dev_hours = round(total_dev_hours - customer_dev_hours, 2)
        customer_dev_pct = (round(customer_dev_hours / total_dev_hours * 100, 1)
                            if total_dev_hours else 0.0)

        # Task counts per backlog stage
        dev_stage_map = [
            ('backlog', 'backlog'),
            ('in_progress', 'in progress'),
            ('acceptance', 'acceptance'),
            ('ready_for_production', 'ready for production'),
        ]
        backlog_by_stage: Dict[str, int] = {}
        for key, stage_name in dev_stage_map:
            backlog_by_stage[key] = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
                'project.task', 'search_count',
                [[('user_ids', 'in', dev_user_ids),
                  ('stage_id.name', 'ilike', stage_name)]])
        backlog_by_stage['total'] = sum(backlog_by_stage.values())

        development_work = {
            'total_hours': total_dev_hours,
            'customer_hours': customer_dev_hours,
            'internal_hours': internal_dev_hours,
            'customer_pct': customer_dev_pct,
            'backlog_by_stage': backlog_by_stage,
        }

        return {
            'period': period,
            'period_label': period_label,
            'customer_service': customer_service,
            'tech_maintenance': tech_maintenance,
            'key_account_management': key_account_management,
            'rd_and_ai': rd_and_ai,
            'development_work': development_work,
        }

    except Exception as e:
        return {'error': f'Error fetching team status: {str(e)}'}


@mcp.tool()
def get_helpdesk_status(period: str = "7d") -> Dict[str, Any]:
    """
    Detailed helpdesk status for the given period.
    Covers ticket volumes, stage breakdown, and the most recently active tickets.

    Period options: "7d" (default), "1m", "1q".

    Use this when asked specifically about customer service, helpdesk health,
    ticket volumes, or support queue — without needing the full team update.

    Returns keys:
        period, period_label, new_tickets, resolved_tickets, open_tickets,
        stage_breakdown (dict stage → count),
        recent_tickets (list with id, name, stage, create_date, write_date, url — up to 20).
    """
    try:
        uid, models = get_odoo_connection()
        base_url = ODOO_URL.rstrip('/')
        start_dt, start_d, days, period_label = _parse_period(period)

        new_count = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'helpdesk.ticket', 'search_count',
            [BASE_TICKET_DOMAIN + [('create_date', '>=', start_dt)]])

        resolved_count = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'helpdesk.ticket', 'search_count',
            [BASE_TICKET_DOMAIN + [
                ('write_date', '>=', start_dt),
                '|', ('stage_id.name', 'ilike', 'solved'),
                     ('stage_id.name', 'ilike', 'approv')
            ]])

        open_count = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'helpdesk.ticket', 'search_count',
            [BASE_TICKET_DOMAIN + [
                ('stage_id.name', 'not ilike', 'solved'),
                ('stage_id.name', 'not ilike', 'approv'),
            ]])

        recent_ids = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'helpdesk.ticket', 'search',
            [BASE_TICKET_DOMAIN + [('write_date', '>=', start_dt)]],
            {'limit': 20, 'order': 'write_date desc'})
        recent_tickets = []
        stage_breakdown: Dict[str, int] = {}
        if recent_ids:
            raw = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
                'helpdesk.ticket', 'read', [recent_ids],
                {'fields': ['id', 'name', 'stage_id', 'create_date', 'write_date']})
            for t in raw:
                sname = t['stage_id'][1] if t.get('stage_id') else 'Unknown'
                stage_breakdown[sname] = stage_breakdown.get(sname, 0) + 1
                recent_tickets.append({
                    'id': t['id'], 'name': t['name'], 'stage': sname,
                    'create_date': t['create_date'], 'write_date': t['write_date'],
                    'url': f"{base_url}/web#id={t['id']}&model=helpdesk.ticket&view_type=form",
                })

        return {
            'period': period, 'period_label': period_label,
            'new_tickets': new_count,
            'resolved_tickets': resolved_count,
            'open_tickets': open_count,
            'stage_breakdown': stage_breakdown,
            'recent_tickets': recent_tickets,
        }

    except Exception as e:
        return {'error': f'Error fetching helpdesk status: {str(e)}'}


@mcp.tool()
def get_team_capacity(period: str = "7d") -> Dict[str, Any]:
    """
    Team capacity overview: timesheet hours logged in the period plus the full
    current backlog per assignee with weeks-to-clear estimates.

    Period options: "7d" (default), "1m", "1q".

    Use this when asked about team workload, capacity, who is busy, missing
    timesheets, customer billing percentage, or how long the backlog will take.

    Returns keys:
        period, period_label,
        hours (total_hours, customer_hours, internal_hours,
               by_employee with total_hours, customer_pct, missing_hours),
        backlog (total_tasks, total_allocated_hours, by_assignee with
                 task_count, allocated_hours, weeks_to_clear, months_to_clear).
    """
    try:
        _, _, days, period_label = _parse_period(period)

        hours_data   = get_team_hours(days)
        backlog_data = get_team_backlog()

        hours_summary = {
            'total_hours':    hours_data.get('total_hours', 0.0),
            'customer_hours': hours_data.get('customer_hours', 0.0),
            'internal_hours': hours_data.get('internal_hours', 0.0),
            'by_employee': [
                {'name': e['employee_name'],
                 'total_hours': e['total_hours'],
                 'customer_pct': e['customer_pct'],
                 'missing_hours': e['missing_hours']}
                for e in (hours_data.get('by_employee') or [])
            ],
        }

        backlog_summary = {
            'total_tasks':           backlog_data.get('total_tasks', 0),
            'total_allocated_hours': backlog_data.get('total_allocated_hours', 0.0),
            'by_assignee': [
                {'assignee': a['assignee'],
                 'task_count': a['task_count'],
                 'allocated_hours': a['allocated_hours'],
                 'weeks_to_clear': a['weeks_to_clear'],
                 'months_to_clear': a['months_to_clear']}
                for a in (backlog_data.get('by_assignee') or [])
            ],
        }

        return {
            'period': period, 'period_label': period_label,
            'hours': hours_summary,
            'backlog': backlog_summary,
        }

    except Exception as e:
        return {'error': f'Error fetching team capacity: {str(e)}'}


@mcp.tool()
def get_sales_activity(period: str = "7d") -> Dict[str, Any]:
    """
    Completed account management and sales activities by the Continuous Services
    team (department 18) on CRM opportunities and customer contacts.

    Period options: "7d" (default), "1m", "1q".

    Use this when asked about CRM pipeline work, customer touchpoints, sales
    actions, account management activities, or prospect follow-ups.

    Returns keys:
        period, period_label, crm_count, partner_count,
        crm_activities (list with date, author, activity_type, lead_name, lead_id, body, url),
        partner_activities (list with date, author, activity_type, partner_name, partner_id, body, url).
    """
    try:
        _, _, days, period_label = _parse_period(period)
        data = get_department_activities(days)
        return {
            'period': period,
            'period_label': period_label,
            **{k: v for k, v in data.items() if k != 'days'},
        }
    except Exception as e:
        return {'error': f'Error fetching sales activity: {str(e)}'}


@mcp.custom_route("/", methods=["GET"])
async def index(request):
    """Health check endpoint for Railway."""
    return JSONResponse({
        "status": "ok",
        "service": "Odoo Helpdesk Agent",
        "version": SERVER_VERSION,
        "author": SERVER_AUTHOR,
        "server_start_time": SERVER_START_TIME,
        "mcp_ready": True
    })

if __name__ == "__main__":
    port_env = os.getenv("PORT")
    if port_env:
        # Production/Cloud mode: Run as SSE server
        port = int(port_env)
        # Using the built-in .run(transport="sse") is more robust as it handles
        # all internal SSE middleware and CORS configuration automatically.
        mcp.run(transport="sse", host="0.0.0.0", port=port)
    else:
        # Local mode: Run using standard I/O (stdio)
        mcp.run(transport="stdio")
