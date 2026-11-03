import discord
from discord import app_commands
from discord.ext import commands
import database

class Config(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="setup", description="Configure Server A, B and C.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        server_b_id="Server B ID (enable Developer Mode to copy it)",
        server_c_id="Optional Server C ID",
        log_channel_id="Optional text channel ID in Server C")
    async def setup(self, interaction: discord.Interaction,
        server_b_id: str, mentorship_role: discord.Role,
        sales_channel: discord.TextChannel,
        role_assigned_channel: discord.TextChannel, role_revoked_channel: discord.TextChannel,
        ticket_category: discord.CategoryChannel, renewal_category: discord.CategoryChannel,
        renewal_url: str, subscription_days: app_commands.Range[int, 1, 365] = 30,
        server_c_id: str | None = None, log_channel_id: str | None = None):
        server_a = interaction.guild
        if server_a is None:
            return await interaction.response.send_message("Run this command inside Server A.", ephemeral=True)
        try:
            b_id = int(server_b_id)
            c_id = int(server_c_id) if server_c_id else None
            log_id = int(log_channel_id) if log_channel_id else None
        except ValueError:
            return await interaction.response.send_message("Server and channel IDs must be numeric Discord IDs.", ephemeral=True)
        if any(x.guild.id != server_a.id for x in
               (mentorship_role, sales_channel, role_assigned_channel, role_revoked_channel, ticket_category, renewal_category)):
            return await interaction.response.send_message("All selected roles and channels must belong to Server A.", ephemeral=True)
        server_b = self.bot.get_guild(b_id)
        if server_b is None:
            return await interaction.response.send_message("The bot must be invited to Server B before setup.", ephemeral=True)
        if c_id is not None:
            server_c = self.bot.get_guild(c_id)
            log_channel = server_c.get_channel(log_id) if server_c and log_id else None
            if not isinstance(log_channel, discord.TextChannel):
                return await interaction.response.send_message("For Server C, provide a valid text channel ID in that server.", ephemeral=True)
        elif log_id is not None:
            return await interaction.response.send_message("Provide Server C ID when configuring its log channel.", ephemeral=True)
        await database.set_config(server_a.id, server_a_id=server_a.id,
            server_b_id=b_id, server_c_id=c_id, mentorship_role_id=mentorship_role.id,
            sales_channel_id=sales_channel.id,
            role_assigned_channel_id=role_assigned_channel.id,
            role_revoked_channel_id=role_revoked_channel.id,
            ticket_category_id=ticket_category.id, renewal_category_id=renewal_category.id,
            log_channel_id=log_id, renewal_url=renewal_url,
            subscription_days=subscription_days)
        await interaction.response.send_message("Configuration saved.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Config(bot))
