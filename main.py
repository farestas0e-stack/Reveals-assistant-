from __future__ import annotations

import asyncio
import logging
import os

import discord
from discord.ext import commands

from database import BotDatabase


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("mentorship_bot")


class MentorshipBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.database = BotDatabase(os.getenv("DATABASE_PATH", "data/bot.sqlite3"))

    async def setup_hook(self) -> None:
        await self.database.initialize()
        logger.info("SQLite database initialized.")
        await self.load_extension("cogs.ticket_manager")
        await self.load_extension("cogs.setup")
        await self.load_extension("cogs.membership")
        await self.load_extension("cogs.moderation")
        await self.load_extension("cogs.admin_tools")
        logger.info("Ticket, setup, membership, moderation and admin extensions loaded.")
        await self.tree.sync()
        logger.info("Application commands synchronized.")

    async def close(self) -> None:
        await super().close()
        await self.database.close()


async def main() -> None:
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        raise RuntimeError(
            "Set the DISCORD_BOT_TOKEN environment variable before starting the bot."
        )
    bot = MentorshipBot()
    async with bot:
        await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
