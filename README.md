# Odoo Helpdesk Agent MCP

**Version:** 2026-04-04 (r3) | **Author:** Svante

A Model Context Protocol (MCP) server that empowers AI assistants (like Claude) to act as expert agents for the Continuous Services team. Covers helpdesk, timesheets, backlog, R&D, and account management activity — all from a single MCP connection.

---

## Tools

Tools are organized in two layers. **Layer 1** answers business questions directly. **Layer 2** goes deeper into specific data.

All tools accept a `period` parameter: `"7d"` (last 7 days, default), `"1m"` (last 30 days), `"1q"` (last 90 days).

---

### Layer 1 — Business Questions

| Tool | What it answers |
| :--- | :--- |
| `get_team_status(period)` | **The primary tool.** Full Continuous Services update across all 4 areas. Always formats output as a 4-section briefing: Customer Service / Tech Maintenance / Key Account Management / R&D & AI. |
| `get_helpdesk_status(period)` | How is the helpdesk doing? Ticket volumes, stage breakdown, recent activity. |
| `get_team_capacity(period)` | How busy is the team? Hours logged + full backlog per assignee with weeks-to-clear estimates. |
| `get_sales_activity(period)` | What account management & sales work happened? Completed activities on CRM opportunities and customer contacts. |

**Default output format for `get_team_status`:**
```
Continuous Services [weekly/monthly/quarterly] update:
1. Customer Service: [3 sentences, max 300 chars, numbers & lists]
2. Tech Maintenance: [3 sentences, max 300 chars, numbers & lists]
3. Key Account Management: [3 sentences, max 300 chars, numbers & lists]
4. R&D & AI: [3 sentences, max 300 chars, numbers & lists]
```

---

### Layer 2 — Deep Dives

| Tool | Description |
| :--- | :--- |
| `get_team_backlog()` | Full task backlog for dept 18, grouped by stage and assignee with weeks/months-to-clear estimates (6 h/day capacity). |
| `get_rd_hours(months)` | Logged R&D timesheet hours by project/task + all open R&D tasks assigned to the team. |
| `get_issues_analysis(months)` | Multi-month trend analysis: most common, most laborious, and highest-priority helpdesk issues. |
| `get_ticket_details(ticket_id)` | Full detail for a single ticket (description, assignee, stage, customer, tags). |
| `get_ticket_conversation(ticket_id)` | Full message and internal note history for a ticket. |
| `get_tickets_for_analysis(start_date, end_date)` | Raw ticket list for a date range — use for custom topic or trend analysis. |
| `search_similar_tickets(query)` | Keyword search across ticket names and descriptions. |
| `get_helpdesk_stages()` | List all helpdesk pipeline stages. |
| `search_odoo_docs(query)` | Google search scoped to `odoo.com/documentation`. |
| `search_odoo_github_code(query)` | Code search in the `odoo/odoo` GitHub repository. |
| `get_server_info()` | Version, author, and connected Odoo instance metadata. |

**Stage semantics (helpdesk):**
- **Solved** — issue resolved and closed.
- **Approval** — work completed, waiting for customer confirmation.
- **Cancelled** — excluded from all results.

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
