# Odoo Helpdesk Agent MCP

**Version:** 2026-04-04 | **Author:** Svante

A Model Context Protocol (MCP) server that empowers AI assistants (like Claude) to act as expert Odoo Helpdesk agents. It bridges the gap between Odoo's Helpdesk module and your AI assistant, providing real-time ticket data, trend analysis, and documentation lookup.

---

## Available Tools

### Helpdesk Tickets
All ticket tools are scoped to **helpdesk team 2** and exclude Cancelled tickets.

| Tool | Description |
| :--- | :--- |
| `search_similar_tickets` | Search tickets by keyword in name and description |
| `get_recent_tickets` | Most recently created tickets, optionally filtered by stage |
| `get_recently_updated_tickets` | Tickets ordered by last modification date |
| `get_ticket_details` | Full detail view of a single ticket by ID |
| `get_ticket_conversation` | Message log and internal notes for a ticket |
| `get_helpdesk_stages` | List all available pipeline stages |
| `get_weekly_activity` | Created and updated ticket counts over N days |
| `get_tickets_for_analysis` | Ticket content for a date range (topic/trend analysis) |
| `get_issues_analysis` | Deep analysis over N months: most common, most laborious, and highest-priority issues with resolution time and tag clustering |

**Stage semantics:**
- **Solved** — issue resolved and closed.
- **Approval** — work completed, waiting for customer confirmation.
- **Cancelled** — excluded from all results (noise).

### Documentation & Code
| Tool | Description |
| :--- | :--- |
| `search_odoo_docs` | Google search scoped to `odoo.com/documentation` |
| `search_odoo_github_code` | Code search in the `odoo/odoo` GitHub repository |

### Server Info
| Tool | Description |
| :--- | :--- |
| `get_server_info` | Returns version, author, and connected Odoo instance metadata |

---

## Cloud Deployment (Railway)

This server is optimized for deployment on [Railway](https://railway.app), using **SSE (Server-Sent Events)** transport for remote connectivity.

### 1. One-Click Setup
1. Fork this repository or push it to your GitHub.
2. Create a **New Project** on Railway and connect it to your GitHub repo.
3. Railway will automatically detect the `Procfile` and `requirements.txt`.

### 2. Environment Variables

| Variable | Required | Description |
| :--- | :---: | :--- |
| `ODOO_URL` | Yes | Your Odoo instance URL (e.g., `https://mycompany.odoo.com`) |
| `ODOO_DB` | Yes | Database name |
| `ODOO_USERNAME` | Yes | Your Odoo login email/username |
| `ODOO_PASSWORD` | Yes | Your Odoo password or **API Key** (Recommended) |
| `GITHUB_TOKEN` | No | GitHub personal access token — raises code search rate limit from ~10 to 5000 req/min |
| `PORT` | Auto | Set automatically by Railway (used for SSE mode) |

### Connecting to Claude

Once deployed, Railway provides a public URL (e.g., `https://mcp-odoo-xfiles-production.up.railway.app`).

#### Option A: Claude Desktop
Add the following to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "odoo-agent": {
      "command": "curl",
      "args": ["-s", "-N", "https://your-app-name.up.railway.app/sse"]
    }
  }
}
```

#### Option B: Claude.ai (Web)
*Requires a Claude Pro, Max, Team, or Enterprise plan.*

1. Open [Claude.ai](https://claude.ai) and go to **Settings** > **Connectors**.
2. Click **Add custom connector**.
3. Name: `Odoo Helpdesk Agent`
4. URL: `https://your-app-name.up.railway.app/sse`
5. Click **Add**.

> Always ensure the URL ends with `/sse`.

---

## Local Development

### Prerequisites
- Python 3.10+
- Odoo 17+ credentials

### Installation

```bash
git clone <your-repo-url>
cd mcp-odoo-xfiles
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Create a `.env` file:

```dotenv
ODOO_URL=https://mycompany.odoo.com
ODOO_DB=mydb
ODOO_USERNAME=admin@example.com
ODOO_PASSWORD=your_api_key_here
GITHUB_TOKEN=ghp_optional_token
```

### Running

```bash
python server.py
```

Test via the MCP Inspector:

```bash
npx @modelcontextprotocol/inspector python server.py
```

---

## Security Notes
- **Never** commit your `.env` file.
- Use **Odoo API Keys** instead of passwords for improved security and audit logging.
- Provide a `GITHUB_TOKEN` to avoid GitHub's unauthenticated rate limit (10 req/min).
- Keep your Railway public URL private if it exposes sensitive business data.

## License
MIT
