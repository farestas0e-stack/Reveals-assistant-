import discord
from discord import app_commands
from discord.ext import commands
import database

class Config(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="setup", description="Configure Server A, B and C.")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup(self, interaction: discord.Interaction,
        server_a: discord.Guild, server_b: discord.Guild,
        mentorship_role: discord.Role, sales_channel: discord.TextChannel,
        audit_channel: discord.TextChannel, ticket_category: discord.CategoryChannel,
        renewal_category: discord.CategoryChannel, renewal_url: str,
        subscription_days: app_commands.Range[int, 1, 365] = 30,
        server_c: discord.Guild | None = None,
        log_channel: discord.TextChannel | None = None):
        if interaction.guild_id != server_a.id:
            return await interaction.response.send_message("Run this in Server A.", ephemeral=True)
        if any(x.guild.id != server_a.id for x in
               (mentorship_role, sales_channel, audit_channel, ticket_category, renewal_category)):
            return await interaction.response.send_message("All selected roles and channels must belong to Server A.", ephemeral=True)
        await database.set_config(server_a.id, server_a_id=server_a.id,
            server_b_id=server_b.id, server_c_id=server_c.id if server_c else None,
            mentorship_role_id=mentorship_role.id, sales_channel_id=sales_channel.id,
            audit_channel_id=audit_channel.id, ticket_category_id=ticket_category.id,
            renewal_category_id=renewal_category.id,
            log_channel_id=log_channel.id if log_channel else None,
            renewal_url=renewal_url, subscription_days=subscription_days)
        await interaction.response.send_message("Configuration saved.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Config(bot))
