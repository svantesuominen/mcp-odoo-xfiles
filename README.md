# Odoo Helpdesk Agent MCP

This is a Model Context Protocol (MCP) server designed to assist Odoo Helpdesk agents. It connects Odoo's Helpdesk module with an AI assistant to streamline ticket resolution.

## Features

- **Search Similar Tickets**: Finds past tickets with similar problems to learn from previous solutions.
- **Get Ticket Context**: Retrieves full conversation history (messages/notes) of tickets.
- **Search Documentation**: Searches official Odoo documentation for standard procedures and answers.
- **Search Source Code**: Searches the Odoo GitHub repository to debug technical issues or error messages.

## Deployment

### Deploy to Railway (Cloud)

This server is configured to run on [Railway](https://railway.app) using the SSE (Server-Sent Events) transport.

1.  **Push code to GitHub**: (Already done in this case).
2.  **Create a New Project on Railway**: Connect it to your GitHub repository.
3.  **Set Environment Variables**: In the Railway dashboard, add the following variables:
    *   `ODOO_URL`
    *   `ODOO_DB`
    *   `ODOO_USERNAME`
    *   `ODOO_PASSWORD`
4.  **Connect from Claude**: Once deployed, Railway will give you a public URL (e.g., `https://your-app.up.railway.app/sse`). Use this URL in your Claude Desktop config:
    ```json
    "odoo-helpdesk-cloud": {
      "command": "curl",
      "args": ["-s", "https://your-app.up.railway.app/sse"]
    }
    ```
    *Note: Connecting to a remote SSE MCP server via curl/stdio bridge is one way, but many modern MCP clients support SSE URLs directly.*

### Local Development

1.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

2.  **Configure Environment**:
    Create a `.env` file from `.env.example`.

3.  **Run with MCP Inspector**:
    ```bash
    npx @modelcontextprotocol/inspector python server.py
    ```
