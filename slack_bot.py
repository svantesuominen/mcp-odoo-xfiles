"""
Slack bot for Continuous Services team status.

Slash commands:
  /weekly    → get_team_status(period="7d",  format="slack")
  /monthly   → get_team_status(period="1m",  format="slack")
  /quarterly → get_team_status(period="1q",  format="slack")

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

# Import directly — no HTTP round-trip needed since we share the same process space
from server import get_team_status


async def _post_status(ack, say, period: str):
    await ack()
    try:
        text = get_team_status(period=period, format="slack")
        await say(text)
    except Exception as e:
        _logger.error("Error fetching team status: %s", e)
        await say(f":warning: Could not fetch team status: {e}")


@app.command("/weekly")
async def cmd_weekly(ack, say):
    await _post_status(ack, say, "7d")


@app.command("/monthly")
async def cmd_monthly(ack, say):
    await _post_status(ack, say, "1m")


@app.command("/quarterly")
async def cmd_quarterly(ack, say):
    await _post_status(ack, say, "1q")


async def main():
    handler = AsyncSocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    _logger.info("Starting Slack bot (Socket Mode)...")
    await handler.start_async()


if __name__ == "__main__":
    asyncio.run(main())
