"""
Slack bot for Continuous Services team status.

Slash commands:
  /weekly    → get_team_status(period="7d",  format="slack")
  /monthly   → get_team_status(period="1m",  format="slack")
  /quarterly → get_team_status(period="1q",  format="slack")
  /coverage1 → get_coverage1 (team alias or person name)

Uses Socket Mode — no public URL required.
Set SLACK_BOT_TOKEN (xoxb-...) and SLACK_APP_TOKEN (xapp-...) in environment.
"""

import asyncio
import logging
import os

from dotenv import load_dotenv
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

load_dotenv()

logging.basicConfig(level=logging.INFO)
_logger = logging.getLogger(__name__)

app = AsyncApp(token=os.environ["SLACK_BOT_TOKEN"])

ALLOWED_CHANNEL = os.environ.get("SLACK_ALLOWED_CHANNEL", "team-x-files")


async def _post_status(ack, say, body, period: str):
    channel = body.get("channel_name", "")
    _logger.info("Slash command received in channel: %r (allowed: %r)", channel, ALLOWED_CHANNEL)
    if ALLOWED_CHANNEL and channel != ALLOWED_CHANNEL:
        await ack(text=f"This command only works in #{ALLOWED_CHANNEL}. (you are in: #{channel})")
        return
    await ack()
    try:
        # Import the raw function (not the FastMCP-wrapped FunctionTool object)
        from server import team_status_fn
        text = team_status_fn(period=period, format="slack")
        await say(text)
    except Exception as e:
        _logger.error("Error fetching team status: %s", e)
        await say(f":warning: Could not fetch team status: {e}")


@app.command("/weekly")
async def cmd_weekly(ack, say, body):
    await _post_status(ack, say, body, "7d")


@app.command("/monthly")
async def cmd_monthly(ack, say, body):
    await _post_status(ack, say, body, "1m")


@app.command("/quarterly")
async def cmd_quarterly(ack, say, body):
    await _post_status(ack, say, body, "1q")


async def _post_coverage1(say, body: dict):
    """Fetch Coverage 1 from Odoo and post (runs after immediate slash-command ack)."""
    try:
        from coverage1 import resolve_slack_target, get_coverage1, format_coverage1_slack

        text = (body.get("text") or "").strip()
        target = resolve_slack_target(text)
        if target.get("error") == "usage":
            await say(target.get("message", "Usage: /coverage1 xfiles | devteam | Name"))
            return
        if target.get("ambiguous") or target.get("error"):
            await say(format_coverage1_slack(target))
            return
        if target.get("mode") == "person":
            result = get_coverage1(employee_id=target["employee_id"], format="slack")
        else:
            result = get_coverage1(
                team_id=target["team_id"],
                extra_user_ids=target.get("extra_user_ids"),
                format="slack",
            )
        await say(result)
    except Exception as e:
        _logger.error("Error fetching coverage1: %s", e)
        await say(f":warning: Could not fetch Coverage 1: {e}")


@app.command("/coverage1")
async def cmd_coverage1(ack, say, body):
    channel = body.get("channel_name", "")
    _logger.info("Slash command /coverage1 in channel: %r", channel)
    if ALLOWED_CHANNEL and channel != ALLOWED_CHANNEL:
        await ack(text=f"This command only works in #{ALLOWED_CHANNEL}. (you are in: #{channel})")
        return
    await ack(text="Computing Coverage 1…")
    asyncio.create_task(_post_coverage1(say, body))


async def main():
    handler = AsyncSocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    _logger.info("Starting Slack bot (Socket Mode)...")
    await handler.start_async()


if __name__ == "__main__":
    asyncio.run(main())
