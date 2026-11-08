import os
import logging
import discord
from discord.ext import commands
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(dotenv_path=os.path.join(BASE_DIR, ".env"), override=False)

# Import after loading .env so DB_PATH is read from the environment.
import database
from superprofile_webhook import SuperProfileWebhookServer

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
log = logging.getLogger("reveals-assistant")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.guilds = True
intents.messages = True

class RevealsBot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.webhook_server = None

    async def setup_hook(self):
        await database.init_db()
        extensions = (
            "cogs.config",
            "cogs.mentorship",
            "cogs.ticketing",
            "cogs.broadcast",
            "cogs.moderation",
            "cogs.embed_sender",
            "cogs.category_tools",
        )
        for extension in extensions:
            await self.load_extension(extension)
            log.info("Loaded extension %s", extension)
        await self.tree.sync()
        log.info("Global application commands synced")
        self.webhook_server = SuperProfileWebhookServer(self)
        await self.webhook_server.start()

    async def close(self):
        if self.webhook_server:
            await self.webhook_server.close()
        await super().close()

bot = RevealsBot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    log.info("Ready as %s (%s)", bot.user, bot.user.id)

if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("Set DISCORD_TOKEN in the hosting environment.")
    bot.run(token, log_handler=None)
