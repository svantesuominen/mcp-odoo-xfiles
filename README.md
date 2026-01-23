# Odoo Helpdesk Agent MCP

This is a Model Context Protocol (MCP) server designed to assist Odoo Helpdesk agents. It connects Odoo's Helpdesk module with an AI assistant to streamline ticket resolution.

## Features

- **Search Similar Tickets**: Finds past tickets with similar problems to learn from previous solutions.
- **Get Ticket Context**: Retrieves full conversation history (messages/notes) of tickets.
- **Search Documentation**: Searches official Odoo documentation for standard procedures and answers.
- **Search Source Code**: Searches the Odoo GitHub repository to debug technical issues or error messages.

## Setup

1.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

2.  **Configure Environment**:
    Copy `.env.example` to `.env` and fill in your Odoo credentials.
    ```bash
    cp .env.example .env
    ```
    
    *   `ODOO_URL`: The URL of your Odoo instance (e.g., `https://mycompany.odoo.com`).
    *   `ODOO_DB`: The database name.
    *   `ODOO_USERNAME`: Your Odoo username (email).
    *   `ODOO_PASSWORD`: Your Odoo password or API Key.

## Usage

Run the server directly (for testing):
```bash
python server.py
```

### Connect to Claude Desktop

Add this to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "odoo-helpdesk": {
      "command": "python",
      "args": ["/absolute/path/to/mcp-odoo-xfiles/server.py"]
    }
  }
}
```
