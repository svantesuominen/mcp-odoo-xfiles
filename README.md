# Odoo Helpdesk Agent MCP

A high-performance Model Context Protocol (MCP) server that empowers AI assistants (like Claude) to act as expert Odoo Helpdesk agents. It bridges the gap between Odoo's CRM/Helpdesk modules and your AI assistant, providing real-time data access and documentation lookup.

## Features

- **Search Similar Tickets**: Intelligent search through historical helpdesk tickets to find proven solutions.
- **Conversation History**: Deep-dive into ticket logs, internal notes, and email history.
- **Documentation Lookup**: Automatic search in official Odoo documentation via Google.
- **Source Code Analysis**: Direct integration with Odoo's GitHub repository for technical debugging.
- **Trend Analysis**: Ability to analyze ticket volumes and topics over custom date ranges.
- **Weekly Activity Reports**: Accurate counts and lists of new and updated tickets over any time window.

---

## Cloud Deployment (Railway)

This server is optimized for deployment on [Railway](https://railway.app), leveraging the **SSE (Server-Sent Events) transport** for remote connectivity.

### 1. One-Click Setup
1. Fork this repository or push it to your GitHub.
2. Create a **New Project** on Railway and connect it to your GitHub repo.
3. Railway will automatically detect the `Procfile` and `requirements.txt`.

### 2. Environment Variables
Configure the following in your Railway project settings:

| Variable | Required | Description |
| :--- | :---: | :--- |
| `ODOO_URL` | Yes | Your Odoo instance URL (e.g., `https://mycompany.odoo.com`) |
| `ODOO_DB` | Yes | Database name |
| `ODOO_USERNAME` | Yes | Your Odoo login email/username |
| `ODOO_PASSWORD` | Yes | Your Odoo password or **API Key** (Recommended) |
| `GITHUB_TOKEN` | No | GitHub personal access token — raises code search rate limit from ~10 to 5000 req/min |
| `PORT` | Auto | Set automatically by Railway (used for SSE mode) |

### Connecting to Claude
Once deployed, Railway will provide a public URL (e.g., `https://mcp-odoo-xfiles-production.up.railway.app`).

#### Option A: Claude Desktop (Standard)
Add the following to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "odoo-agent": {
      "command": "curl",
      "args": [
        "-s",
        "-N",
        "https://your-app-name.up.railway.app/sse"
      ]
    }
  }
}
```

#### Option B: Claude.ai (Web Version)
*Note: Requires a Claude Pro, Max, Team, or Enterprise plan.*

1.  Open [Claude.ai](https://claude.ai) and click your **Profile Icon**.
2.  Go to **Settings** > **Connectors**.
3.  Click **Add custom connector**.
4.  Enter the Name: **Odoo Helpdesk Agent**
5.  Enter your Railway public URL with the `/sse` path:
    `https://your-app-name.up.railway.app/sse`
6.  Click **Add**. Claude will now have access to your Odoo tools!

> **Pro Tip:** Always ensure the URL ends with `/sse` for the connection to work correctly.

---

## Local Development

### Prerequisites
- Python 3.10+
- Odoo 17+ credentials

### Installation
1. Clone the repo and enter the directory:
   ```bash
   git clone <your-repo-url>
   cd mcp-odoo-xfiles
   ```

2. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Setup environment:
   Create a `.env` file with the variables listed in the table above.

   ```dotenv
   ODOO_URL=https://mycompany.odoo.com
   ODOO_DB=mydb
   ODOO_USERNAME=admin@example.com
   ODOO_PASSWORD=your_api_key_here
   GITHUB_TOKEN=ghp_optional_token
   ```

### Running
To run the server in standard I/O mode (default for local):
```bash
python server.py
```

To test via the **MCP Inspector**:
```bash
npx @modelcontextprotocol/inspector python server.py
```

---

## Security Notes
- **Never** commit your `.env` file.
- Use **Odoo API Keys** instead of regular passwords whenever possible for improved security and audit logging.
- Provide a `GITHUB_TOKEN` to avoid hitting GitHub's unauthenticated code search rate limit (10 req/min).
- Ensure your Railway app's public URL is kept private or properly secured if sensitive data is exposed.

## License
MIT
