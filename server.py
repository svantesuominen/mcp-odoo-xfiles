import os
import sys
import xmlrpc.client
from typing import List, Dict, Any, Union
from fastmcp import FastMCP
from dotenv import load_dotenv
from googlesearch import search as google_search
import requests
from datetime import datetime, timedelta
from starlette.responses import JSONResponse

# Load environment variables
load_dotenv()

# Configuration
ODOO_URL = os.getenv("ODOO_URL")
ODOO_DB = os.getenv("ODOO_DB")
ODOO_USERNAME = os.getenv("ODOO_USERNAME")
ODOO_PASSWORD = os.getenv("ODOO_PASSWORD") or os.getenv("ODOO_API_KEY")

# Initialize MCP
mcp = FastMCP("The X-Files ASteroid")

def get_odoo_connection():
    if not all([ODOO_URL, ODOO_DB, ODOO_USERNAME, ODOO_PASSWORD]):
        raise ValueError("Missing Odoo credentials in environment variables")
    
    # Ensure URL doesn't end with slash for consistency
    url = ODOO_URL.rstrip('/')
    
    common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
    try:
        uid = common.authenticate(ODOO_DB, ODOO_USERNAME, ODOO_PASSWORD, {})
        if not uid:
             raise PermissionError("Authentication failed. Please check your credentials.")
        models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")
        return uid, models
    except Exception as e:
        raise ConnectionError(f"Failed to connect to Odoo: {str(e)}")

@mcp.tool()
def search_similar_tickets(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Search for existing helpdesk tickets that might be similar to the problem.
    Searches in ticket name and description.
    Returns keys: id, name, stage_id, description, create_date, url.
    ALWAYS include the 'url' in your response so the user can access the ticket directly.
    """
    try:
        uid, models = get_odoo_connection()
        
        # Search domain: Name OR Description matches query
        domain = ['|', ('name', 'ilike', query), ('description', 'ilike', query)]
        
        ticket_ids = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'helpdesk.ticket', 'search',
            [domain],
            {'limit': limit})
        
        if not ticket_ids:
            return []
            
    # Updated fields list to include assignee, customer, and priority
        fields = ['id', 'name', 'stage_id', 'user_id', 'partner_id', 'priority', 'description', 'create_date']
        
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
    Get the most recent helpdesk tickets.
    Can be filtered by stage_id if provided.
    Returns keys: id, name, stage_id, user_id (assignee), partner_id (customer), priority, create_date, url.
    ALWAYS include the 'url' in your response so the user can access the ticket directly.
    """
    try:
        uid, models = get_odoo_connection()
        
        domain = []
        if stage_id:
            domain.append(('stage_id', '=', stage_id))
            
        ticket_ids = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'helpdesk.ticket', 'search',
            [domain],
            {'limit': limit, 'order': 'create_date desc'})
            
        if not ticket_ids:
            return []
            
        fields = ['id', 'name', 'stage_id', 'user_id', 'partner_id', 'priority', 'create_date']
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

    except Exception as e:
        return [{"error": f"Error fetching recent tickets: {str(e)}"}]

@mcp.tool()
def get_recently_updated_tickets(limit: int = 10) -> List[Dict[str, Any]]:
    """
    Get tickets that have been modified (or had messages sent) recently.
    Useful for seeing active discussions or changes.
    Returns keys: id, name, stage_id, user_id, partner_id, priority, write_date, create_date, url.
    ALWAYS include the 'url' in your response so the user can access the ticket directly.
    """
    try:
        uid, models = get_odoo_connection()
        
        ticket_ids = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'helpdesk.ticket', 'search',
            [[]],
            {'limit': limit, 'order': 'write_date desc'})
            
        if not ticket_ids:
            return []
            
        fields = ['id', 'name', 'stage_id', 'user_id', 'partner_id', 'priority', 'write_date', 'create_date']
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
    Returns keys: days_analyzed, new_tickets_count, updated_tickets_count, new_tickets (list with url), active_tickets (list with url).
    ALWAYS include the ticket 'url' when listing specific tickets so the user can access them directly.
    """
    try:
        uid, models = get_odoo_connection()
        
        # Calculate date threshold
        date_threshold = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
        
        # 1. Tickets Created
        created_domain = [('create_date', '>=', date_threshold)]
        created_ids = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'helpdesk.ticket', 'search',
            [created_domain],
            {'limit': 50, 'order': 'create_date desc'}) # Limit to prevent overflow
            
        # 2. Tickets Updated (excluding created ones if you want, but seeing both is fine)
        # We query for write_date >= threshold
        updated_domain = [('write_date', '>=', date_threshold)]
        updated_ids = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'helpdesk.ticket', 'search',
            [updated_domain],
            {'limit': 50, 'order': 'write_date desc'})
            
        fields = ['id', 'name', 'stage_id', 'user_id', 'priority', 'create_date', 'write_date']
        
        created_tickets = []
        if created_ids:
            created_tickets = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD, 'helpdesk.ticket', 'read', [created_ids], {'fields': fields})

        updated_tickets = []
        if updated_ids:
            updated_tickets = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD, 'helpdesk.ticket', 'read', [updated_ids], {'fields': fields})
            
        base_url = ODOO_URL.rstrip('/')
        
        # Helper to add URL
        def add_url(tlist):
            for t in tlist:
                t['url'] = f"{base_url}/web#id={t['id']}&model=helpdesk.ticket&view_type=form"
                
        add_url(created_tickets)
        add_url(updated_tickets)

        return {
            "days_analyzed": days,
            "new_tickets_count": len(created_ids),
            "updated_tickets_count": len(updated_ids),
            "new_tickets": created_tickets,
            "active_tickets": updated_tickets
        }

    except Exception as e:
        return {"error": f"Error fetching weekly activity: {str(e)}"}

@mcp.tool()
def get_ticket_details(ticket_id: int) -> Dict[str, Any]:
    """
    Get full details for a specific ticket including description, assignee, stage, customer info, etc.
    Returns complete ticket object including 'url'.
    ALWAYS include the 'url' in your response so the user can access the ticket directly.
    """
    try:
        uid, models = get_odoo_connection()
        
        fields = [
            'id', 'name', 'description', 'stage_id', 'user_id', 
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
    try:
        # Search specifically in Odoo documentation
        search_query = f"site:odoo.com/documentation {query}"
        # googlesearch-python's generic search returns simple URLs if advanced=False
        # Using advanced=True to get Title/Desc if possible, depending on library version installed.
        # Fallback to simple strings if advanced not available or behaves differently.
        
        # Safe usage: just URLs first, or try/except.
        # Let's stick to simple strings which is safest with basic deps.
        search_results = google_search(search_query, num_results=limit, advanced=True)
        
        for result in search_results:
            results.append(f"Title: {result.title}\nURL: {result.url}\nDescription: {result.description}")
            
    except TypeError:
        # Fallback for older library version
        try:
            search_results = google_search(search_query, num_results=limit)
            for res in search_results:
                results.append(f"URL: {res}")
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
    
    Args:
        start_date: Start date in 'YYYY-MM-DD' format.
        end_date: Optional end date in 'YYYY-MM-DD' format. If not provided, defaults to today.
        limit: Maximum number of tickets to analyze (default 50).
        
    Returns:
        List of tickets with name, description, tags, and create_date to be used for summarization.
        Includes 'url' for reference.
    """
    try:
        uid, models = get_odoo_connection()
        
        # Format dates for Odoo domain
        # We append time to make sure we cover the full days
        domain_start = f"{start_date} 00:00:00"
        
        if end_date:
            domain_end = f"{end_date} 23:59:59"
        else:
            domain_end = datetime.now().strftime('%Y-%m-%d 23:59:59')
            
        domain = [
            ('create_date', '>=', domain_start),
            ('create_date', '<=', domain_end)
        ]
        
        # Search
        ticket_ids = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
            'helpdesk.ticket', 'search',
            [domain],
            {'limit': limit, 'order': 'create_date desc'})
            
        if not ticket_ids:
            return []
            
        # Read fields relevant for topic analysis
        fields = ['id', 'name', 'description', 'create_date', 'stage_id', 'priority', 'tag_ids']
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

@mcp.custom_route("/", methods=["GET"])
async def index(request):
    """Health check endpoint for Railway."""
    return JSONResponse({
        "status": "ok", 
        "service": "The X-Files ASteroid",
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
