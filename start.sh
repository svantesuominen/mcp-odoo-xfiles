#!/bin/sh
# Start Slack bot in background (only if tokens are set)
if [ -n "$SLACK_BOT_TOKEN" ] && [ -n "$SLACK_APP_TOKEN" ]; then
    python slack_bot.py &
    echo "Slack bot started (pid $!)"
fi

# Start MCP server in foreground
exec python server.py
