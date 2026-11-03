import discord
from discord import app_commands
from discord.ext import commands

class Broadcast(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="broadcast", description="Broadcast a message to all text channels in a category.")
    @app_commands.checks.has_permissions(administrator=True)
    async def broadcast(self, interaction: discord.Interaction,
                        category: discord.CategoryChannel, message: str):
        await interaction.response.defer(ephemeral=True)
        sent = skipped = failed = 0
        for channel in category.text_channels:
            permissions = channel.permissions_for(interaction.guild.me)
            if not permissions.view_channel or not permissions.send_messages:
                skipped += 1
                continue
            try:
                await channel.send(message)
                sent += 1
            except discord.HTTPException:
                failed += 1
        await interaction.followup.send(
            f"Broadcast finished. Sent: {sent}; skipped: {skipped}; failed: {failed}.",
            ephemeral=True)

async def setup(bot):
    await bot.add_cog(Broadcast(bot))
