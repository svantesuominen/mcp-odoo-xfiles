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

@mcp.tool()
def get_recent_tickets(limit: int = 5, stage_id: int = None) -> List[Dict[str, Any]]:
    """
    Get the most recent helpdesk tickets, ordered by creation date.
    Can be filtered by stage_id if provided. Scoped to team 2; cancelled tickets are excluded.
    Stages "Solved" and "Approval" indicate resolved tickets.
    Returns keys: id, name, stage_id, team_id, user_id (assignee), partner_id (customer), priority, create_date, url.
    ALWAYS include the 'url' in your response so the user can access the ticket directly.
    """
    try:
        uid, models = get_odoo_connection()

        domain = list(BASE_TICKET_DOMAIN)
        if stage_id:
            domain.append(('stage_id', '=', stage_id))

        ticket_ids = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'helpdesk.ticket', 'search',
            [domain],
            {'limit': limit, 'order': 'create_date desc'})

        if not ticket_ids:
            return []

        fields = ['id', 'name', 'stage_id', 'team_id', 'user_id', 'partner_id', 'priority', 'create_date']
        tickets = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'helpdesk.ticket', 'read',
            [ticket_ids],
            {'fields': fields})
            
        base_url = ODOO_URL.rstrip('/')
        for ticket in tickets:
            ticket['url'] = f"{base_url}/web#id={ticket['id']}&model=helpdesk.ticket&view_type=form"
            
        return tickets
    except Exception as e:
        return [{"error": f"Error fetching recent tickets: {str(e)}"}]

@mcp.tool()
def get_recently_updated_tickets(limit: int = 10) -> List[Dict[str, Any]]:
    """
    Get tickets that have been modified (or had messages sent) recently.
    Useful for seeing active discussions or changes. Scoped to team 2; cancelled tickets are excluded.
    Returns keys: id, name, stage_id, team_id, user_id, partner_id, priority, write_date, create_date, url.
    ALWAYS include the 'url' in your response so the user can access the ticket directly.
    """
    try:
        uid, models = get_odoo_connection()

        ticket_ids = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'helpdesk.ticket', 'search',
            [BASE_TICKET_DOMAIN],
            {'limit': limit, 'order': 'write_date desc'})

        if not ticket_ids:
            return []

        fields = ['id', 'name', 'stage_id', 'team_id', 'user_id', 'partner_id', 'priority', 'write_date', 'create_date']
        tickets = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'helpdesk.ticket', 'read',
            [ticket_ids],
            {'fields': fields})
            
        base_url = ODOO_URL.rstrip('/')
        for ticket in tickets:
            ticket['url'] = f"{base_url}/web#id={ticket['id']}&model=helpdesk.ticket&view_type=form"
            
        return tickets
    except Exception as e:
        return [{"error": f"Error fetching recently updated tickets: {str(e)}"}]

@mcp.tool()
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
                  timesheet_tasks (task + hours), open_tasks (task + stage + planned_hours + url)).
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
        task_domain = [('project_id.name', 'ilike', 'r&d')]
        if dept18_user_ids:
            task_domain.append(('user_ids', 'in', dept18_user_ids))
        open_tasks = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'project.task', 'search_read',
            [task_domain],
            {'fields': ['id', 'name', 'project_id', 'stage_id', 'planned_hours'], 'limit': 500})

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
                'planned_hours': task.get('planned_hours') or 0.0,
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


@mcp.tool()
def get_team_hours(months: int = 1) -> Dict[str, Any]:
    """
    Fetch all timesheet entries for the Continuous Services team (department 18)
    for the last N months (default 1). Splits hours into customer hours
    (projects with a customer/partner set) vs internal hours.

    Use this when asked about team workload, customer vs internal hours,
    billable hours, or individual utilisation.

    Returns keys:
        period_months, start_date, total_hours, customer_hours, internal_hours,
        by_employee (list with employee_id, employee_name, total_hours,
                     customer_hours, internal_hours).
    """
    try:
        uid, models = get_odoo_connection()
        start_date = (datetime.now() - timedelta(days=30 * months)).strftime('%Y-%m-%d')

        # Step 1: Fetch timesheet lines for dept 18
        ts_domain = [
            ('employee_id.department_id', '=', 18),
            ('date', '>=', start_date),
        ]
        ts_lines = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'account.analytic.line', 'search_read',
            [ts_domain],
            {'fields': ['unit_amount', 'project_id', 'employee_id'], 'limit': 5000})

        if not ts_lines:
            return {
                'period_months': months, 'start_date': start_date,
                'total_hours': 0.0, 'customer_hours': 0.0, 'internal_hours': 0.0,
                'by_employee': []
            }

        # Step 2: Resolve which projects have a customer (single bulk read)
        all_proj_ids = list({line['project_id'][0] for line in ts_lines if line.get('project_id')})
        proj_records = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'project.project', 'read',
            [all_proj_ids], {'fields': ['id', 'partner_id']})
        customer_project_ids = {p['id'] for p in proj_records if p.get('partner_id')}

        # Step 3: Aggregate by employee
        emp_data: Dict[int, Dict] = {}
        for line in ts_lines:
            if not line.get('employee_id'):
                continue
            eid, ename = line['employee_id']
            hours = line['unit_amount']
            if eid not in emp_data:
                emp_data[eid] = {'employee_name': ename, 'total_hours': 0.0,
                                 'customer_hours': 0.0, 'internal_hours': 0.0}
            emp_data[eid]['total_hours'] = round(emp_data[eid]['total_hours'] + hours, 2)
            pid = line['project_id'][0] if line.get('project_id') else None
            if pid and pid in customer_project_ids:
                emp_data[eid]['customer_hours'] = round(emp_data[eid]['customer_hours'] + hours, 2)
            else:
                emp_data[eid]['internal_hours'] = round(emp_data[eid]['internal_hours'] + hours, 2)

        by_employee = sorted(
            [{'employee_id': eid, **data} for eid, data in emp_data.items()],
            key=lambda x: x['total_hours'], reverse=True
        )
        total = round(sum(e['total_hours'] for e in by_employee), 2)
        cust  = round(sum(e['customer_hours'] for e in by_employee), 2)
        intl  = round(sum(e['internal_hours'] for e in by_employee), 2)

        return {
            'period_months': months,
            'start_date': start_date,
            'total_hours': total,
            'customer_hours': cust,
            'internal_hours': intl,
            'by_employee': by_employee
        }

    except Exception as e:
        return {'error': f'Error fetching team hours: {str(e)}'}


@mcp.tool()
def get_team_backlog() -> Dict[str, Any]:
    """
    Current snapshot of all project tasks assigned to members of the
    Continuous Services team (department 18), grouped by stage with planned hours.

    Use this when asked about the team's current workload, backlog size,
    capacity, or task distribution across pipeline stages.

    Returns keys:
        total_tasks, total_planned_hours,
        stages (list with stage_id, stage_name, task_count, planned_hours,
                tasks (list with id, name, project_name, planned_hours, url)).
    """
    try:
        uid, models = get_odoo_connection()
        base_url = ODOO_URL.rstrip('/')

        # Step 1: Resolve dept 18 user IDs (Many2many traversal not reliable — do it safely)
        employees = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'hr.employee', 'search_read',
            [[('department_id', '=', 18)]],
            {'fields': ['user_id'], 'limit': 200})
        user_ids = [e['user_id'][0] for e in employees if e.get('user_id')]

        if not user_ids:
            return {'total_tasks': 0, 'total_planned_hours': 0.0, 'stages': []}

        # Step 2: Fetch tasks assigned to those users
        tasks = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'project.task', 'search_read',
            [[('user_ids', 'in', user_ids)]],
            {'fields': ['id', 'name', 'stage_id', 'planned_hours', 'project_id'], 'limit': 1000})

        # Step 3: Group by stage
        stage_data: Dict[int, Dict] = {}
        for task in tasks:
            if not task.get('stage_id'):
                continue
            sid, sname = task['stage_id']
            if sid not in stage_data:
                stage_data[sid] = {'stage_name': sname, 'tasks': []}
            proj_name = task['project_id'][1] if task.get('project_id') else ''
            stage_data[sid]['tasks'].append({
                'id': task['id'],
                'name': task['name'],
                'project_name': proj_name,
                'planned_hours': task.get('planned_hours') or 0.0,
                'url': f"{base_url}/web#id={task['id']}&model=project.task&view_type=form"
            })

        stages = []
        for sid, data in stage_data.items():
            planned = round(sum(t['planned_hours'] for t in data['tasks']), 2)
            stages.append({
                'stage_id': sid,
                'stage_name': data['stage_name'],
                'task_count': len(data['tasks']),
                'planned_hours': planned,
                'tasks': sorted(data['tasks'], key=lambda t: t['planned_hours'], reverse=True)
            })

        # Sort stages by task count descending
        stages.sort(key=lambda s: s['task_count'], reverse=True)

        total_tasks = sum(s['task_count'] for s in stages)
        total_hours = round(sum(s['planned_hours'] for s in stages), 2)

        return {
            'total_tasks': total_tasks,
            'total_planned_hours': total_hours,
            'stages': stages
        }

    except Exception as e:
        return {'error': f'Error fetching team backlog: {str(e)}'}


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
