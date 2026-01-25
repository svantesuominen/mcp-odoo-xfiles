# Odoo Helpdesk Agent MCP

A high-performance Model Context Protocol (MCP) server that empowers AI assistants (like Claude) to act as expert Odoo Helpdesk agents. It bridges the gap between Odoo's CRM/Helpdesk modules and your AI assistant, providing real-time data access and documentation lookup.

## Features

- **Search Similar Tickets**: Intelligent search through historical helpdesk tickets to find proven solutions.
- **Conversation History**: Deep-dive into ticket logs, internal notes, and email history.
- **Documentation Link**: Automatic lookup in official Odoo documentation.
- **Source Code Analysis**: Direct integration with Odoo's GitHub repository for technical debugging.
- **Trend Analysis**: Ability to analyze ticket volumes and topics over custom date ranges.

---

## Cloud Deployment (Railway)

This server is optimized for deployment on [Railway](https://railway.app), leveraging the **SSE (Server-Sent Events) transport** for remote connectivity.

### 1. One-Click Setup
1. Fork this repository or push it to your GitHub.
2. Create a **New Project** on Railway and connect it to your GitHub repo.
3. Railway will automatically detect the `Procfile` and `requirements.txt`.

### 2. Environment Variables
Configure the following in your Railway project settings:

| Variable | Description |
| :--- | :--- |
| `ODOO_URL` | Your Odoo instance URL (e.g., `https://mycompany.odoo.com`) |
| `ODOO_DB` | Database name |
| `ODOO_USERNAME` | Your Odoo login email/username |
| `ODOO_PASSWORD` | Your Odoo password or **API Key** (Recommended) |
| `PORT` | Set automatically by Railway (used for SSE mode) |

### Connecting to Claude
Once deployed, Railway will provide a public URL (e.g., `https://mcp-odoo-production.up.railway.app`).

#### Option A: Claude Desktop (Standard)
Add the following to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "odoo-agent-cloud": {
      "command": "curl",
      "args": [
        "-s",
        "-N",
        "https://your-railway-app.up.railway.app/sse"
      ]
    }
  }
}
```

#### Option B: Claude.ai (Web Version)
*Note: Requires a Claude Pro, Max, Team, or Enterprise plan.*

1.  Open [Claude.ai](https://claude.ai) and click your **Profile Icon**.
2.  Go to **Settings** > **Integrations** (or **Connectors**).
3.  Scroll to the bottom and click **Add custom connector** (or "Add more").
4.  Enter your Railway public SSE URL: `https://your-railway-app.up.railway.app/sse`
5.  Click **Add**. Claude will now have access to your Odoo tools directly in the web chat!

> **Pro Tip:** Modern MCP clients can connect directly to the SSE URL without needing the `curl` bridge.

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
   Create a `.env` file based on `.env.example`.

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

## Security Note
- **Never** commit your `.env` file.
- Use **Odoo API Keys** instead of regular passwords whenever possible for improved security and audit logging.
- Ensure your Railway app's public URL is kept private or properly secured if sensitive data is exposed.

## License
MIT
