#!/bin/sh
echo "=== start.sh: SLACK_BOT_TOKEN set: $([ -n "$SLACK_BOT_TOKEN" ] && echo yes || echo no) ==="
echo "=== start.sh: SLACK_APP_TOKEN set: $([ -n "$SLACK_APP_TOKEN" ] && echo yes || echo no) ==="

# Start Slack bot in background (only if tokens are set)
if [ -n "$SLACK_BOT_TOKEN" ] && [ -n "$SLACK_APP_TOKEN" ]; then
    python slack_bot.py &
    echo "=== start.sh: Slack bot started (pid $!) ==="
else
    echo "=== start.sh: Slack tokens missing, skipping bot ==="
fi

# Start MCP server in foreground
exec python server.py
