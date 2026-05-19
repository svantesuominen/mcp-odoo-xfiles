# Odoo Helpdesk Agent MCP

**Version:** 2026-04-04 (r4) | **Author:** Svante

A Model Context Protocol (MCP) server that empowers AI assistants (like Claude) to act as expert agents for the Continuous Services team. Covers helpdesk, timesheets, backlog, R&D, and account management activity — all from a single MCP connection.

Also includes a **Slack bot** (Sätkä-Scully) that posts pre-formatted team status updates directly to a Slack channel — no LLM required.

---

## Tools

Tools are organized in two layers. **Layer 1** answers business questions directly. **Layer 2** goes deeper into specific data.

All tools accept a `period` parameter: `"7d"` (last 7 days, default), `"1m"` (last 30 days), `"1q"` (last 90 days).

---

### Layer 1 — Business Questions

| Tool | What it answers |
| :--- | :--- |
| `get_team_status(period)` | **The primary tool.** Full Continuous Services update across 6 sections. Returns structured JSON for Claude, or a Slack-formatted string when called with `format="slack"`. |
| `get_helpdesk_status(period)` | How is the helpdesk doing? Ticket volumes, stage breakdown, recent activity. |
| `get_team_capacity(period)` | How busy is the team? Hours logged + full backlog per assignee with weeks-to-clear estimates. |
| `get_sales_activity(period)` | What account management & sales work happened? Completed activities on CRM opportunities and customer contacts. |

**`get_team_status` output sections:**
```
Continuous Services [weekly/monthly/quarterly] update (Mon 28.3. – Sun 3.4.):
1. Customer Service      — new/resolved tickets, open by stage, recent issues
2. Tech Maintenance      — logged hours, connectivity status, infra backlog
3. Key Account Management — CRM and partner activities, top leads/accounts
4. R&D & AI              — logged hours, tasks worked on
5. Development Work Done — total/customer hours, estimated income, per person
6. Development Work Todo — backlog remaining hours, per-person days of work
```

---

### Layer 2 — Deep Dives

| Tool | Description |
| :--- | :--- |
| `get_client_summary(client_name, years_back)` | Full client dossier: CRM chatter, first sale, projects/hours, active subscription SOs, helpdesk — use with `.cursor/skills/client-summary`. |
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

## Slack Bot (Sätkä-Scully)

A Slack bot that posts pre-formatted team status directly to a channel using slash commands. No LLM in between — data is fetched from Odoo and formatted deterministically.

### Slash commands

| Command | Description |
| :--- | :--- |
| `/weekly` | Last 7 days status |
| `/monthly` | Last 30 days status |
| `/quarterly` | Last 90 days status |

Commands are restricted to the channel set in `SLACK_ALLOWED_CHANNEL` (default: `team-x-files`).

### Slack app setup (one-time)

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → Create New App → From scratch
2. **App Home** → enable "Allow users to send Slash commands and messages from the messages tab" + add a bot user
3. **Socket Mode** → Enable → Generate App-Level Token (scope: `connections:write`) → copy as `SLACK_APP_TOKEN`
4. **Slash Commands** → Add `/weekly`, `/monthly`, `/quarterly`
5. **OAuth & Permissions** → add Bot Token Scopes: `chat:write`, `commands` → Install to workspace → copy Bot Token as `SLACK_BOT_TOKEN`
6. Add both tokens to Railway environment variables

---

## Cloud Deployment (Railway)

This server is optimized for deployment on [Railway](https://railway.app), using **SSE (Server-Sent Events)** transport for remote MCP connectivity. The Slack bot starts automatically as a background process when the Slack tokens are present.

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
| `ODOO_PASSWORD` | Yes | Your Odoo password or **API Key** (recommended) |
| `SLACK_BOT_TOKEN` | No | Slack bot token (`xoxb-...`) for the Slack bot |
| `SLACK_APP_TOKEN` | No | Slack app-level token (`xapp-...`) for Socket Mode |
| `SLACK_ALLOWED_CHANNEL` | No | Channel name where slash commands are accepted (default: `team-x-files`) |
| `GITHUB_TOKEN` | No | GitHub personal access token — raises code search rate limit from ~10 to 5000 req/min |
| `PORT` | Auto | Set automatically by Railway (used for SSE mode) |

### Connecting Claude to the MCP server

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

### Second service: Odoo Sales Capture MCP (`sales_mcp`)

CRM note logging from pasted call/meeting summaries (`search_partner`, `search_lead`, `log_note`). Runs as a **separate** Railway service so you get a **second** public URL and a **separate** Claude connector.

1. In the same Railway project (or a new one), **New** → **GitHub Repo** → select this repo again.
2. **Settings** → set **Start Command** to: `python -m sales_mcp`  
   (Do **not** use `start.sh` here — that is only for the helpdesk MCP.)
3. Copy the same **`ODOO_*`** variables as the helpdesk service. Optional: `ODOO_CALL_ACTIVITY_TYPE_NAME`, `ODOO_MEETING_ACTIVITY_TYPE_NAME`, `ODOO_SALES_DATE_TZ` (see `.env.example`).
4. Enable **public networking** and note the URL, e.g. `https://your-sales-service.up.railway.app`.
5. **Claude:** add another custom connector (Desktop or Web) with URL  
   `https://your-sales-service.up.railway.app/sse`  
   and a distinct name, e.g. `Odoo Sales Capture`.

Health check (JSON): open the service root URL without `/sse` in a browser.

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
# Optional Slack bot
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
SLACK_ALLOWED_CHANNEL=team-x-files
```

### Running

```bash
# Helpdesk MCP only
python server.py

# Sales CRM MCP only (separate process / second deploy)
python -m sales_mcp

# Slack bot only
python slack_bot.py

# Helpdesk MCP + Slack bot (as Railway default service does)
sh start.sh
```

Test the MCP server via the Inspector:

```bash
npx @modelcontextprotocol/inspector python server.py
```

---

## Development process

1. **Plan** — discuss the change and agree on approach
2. **Change** — implement in code
3. **Test locally** — verify with the venv before deploying
4. **Deploy** — commit and push only after explicit approval

---

## Security Notes
- **Never** commit your `.env` file.
- Use **Odoo API Keys** instead of passwords for improved security and audit logging.
- Provide a `GITHUB_TOKEN` to avoid GitHub's unauthenticated rate limit (10 req/min).
- Keep your Railway public URL private if it exposes sensitive business data.

## License
MIT
