import discord
from discord import app_commands
from discord.ext import commands

class Broadcast(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="broadcast", description="Broadcast to every text channel in a category.")
    @app_commands.checks.has_permissions(administrator=True)
    async def broadcast(self, interaction: discord.Interaction, category: discord.CategoryChannel,
                        message: str, mention_users: bool = False):
        await interaction.response.defer(ephemeral=True)
        sent = skipped = failed = 0
        for channel in category.text_channels:
            perms = channel.permissions_for(interaction.guild.me)
            if not perms.view_channel or not perms.send_messages:
                skipped += 1
                continue
            try:
                await channel.send(message, allowed_mentions=discord.AllowedMentions(users=mention_users,
                    roles=False, everyone=False))
                sent += 1
            except discord.HTTPException:
                failed += 1
        await interaction.followup.send(
            f"Broadcast finished — sent {sent}, skipped {skipped}, failed {failed}.",
            ephemeral=True)

async def setup(bot):
    await bot.add_cog(Broadcast(bot))
