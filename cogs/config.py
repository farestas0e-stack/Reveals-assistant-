import discord
from discord import app_commands
from discord.ext import commands
import database

def valid_url(value: str) -> bool:
    return value.startswith(("https://", "http://"))

class Config(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="setup", description="Configure Servers A/B/C and membership checkout.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(server_b_id="Server B numeric ID", mentorship_role_id="Mentorship role ID",
        sales_channel_id="Sales log channel ID", role_assigned_channel_id="Role assigned log channel ID",
        role_revoked_channel_id="Role revoked log channel ID", ticket_category_id="Ticket category ID",
        renewal_category_id="Renewal category ID", monthly_url="Monthly checkout URL",
        quarterly_url="Quarterly checkout URL", staff_role_id="Optional staff role ID",
        server_c_id="Optional Server C ID", log_channel_id="Optional Server C log channel ID")
    async def setup(self, interaction: discord.Interaction, server_b_id: str,
        mentorship_role_id: str, sales_channel_id: str, role_assigned_channel_id: str,
        role_revoked_channel_id: str, ticket_category_id: str, renewal_category_id: str,
        monthly_url: str, quarterly_url: str, staff_role_id: str | None = None,
        server_c_id: str | None = None, log_channel_id: str | None = None):
        guild = interaction.guild
        if guild is None:
            return await interaction.response.send_message("Run this in Server A.", ephemeral=True)
        try:
            ids = [int(x) for x in (server_b_id, mentorship_role_id, sales_channel_id,
                role_assigned_channel_id, role_revoked_channel_id, ticket_category_id, renewal_category_id)]
            b_id, role_id, sales_id, assigned_id, revoked_id, ticket_cat_id, renewal_cat_id = ids
            staff_id = int(staff_role_id) if staff_role_id else None
            c_id = int(server_c_id) if server_c_id else None
            log_id = int(log_channel_id) if log_channel_id else None
        except ValueError:
            return await interaction.response.send_message("Every supplied ID must be numeric.", ephemeral=True)
        if not valid_url(monthly_url) or not valid_url(quarterly_url):
            return await interaction.response.send_message("Monthly and Quarterly URLs must start with http:// or https://.", ephemeral=True)
        role = guild.get_role(role_id)
        sales = guild.get_channel(sales_id)
        assigned = guild.get_channel(assigned_id)
        revoked = guild.get_channel(revoked_id)
        ticket_cat = guild.get_channel(ticket_cat_id)
        renewal_cat = guild.get_channel(renewal_cat_id)
        if not isinstance(role, discord.Role) or not all(isinstance(x, discord.TextChannel) for x in (sales,assigned,revoked)):
            return await interaction.response.send_message("One or more role/channel IDs are invalid for Server A.", ephemeral=True)
        if not isinstance(ticket_cat, discord.CategoryChannel) or not isinstance(renewal_cat, discord.CategoryChannel):
            return await interaction.response.send_message("Ticket and renewal category IDs must identify categories in Server A.", ephemeral=True)
        if staff_id and guild.get_role(staff_id) is None:
            return await interaction.response.send_message("Staff role ID is invalid.", ephemeral=True)
        if self.bot.get_guild(b_id) is None:
            return await interaction.response.send_message("Invite the bot to Server B first.", ephemeral=True)
        if c_id and (self.bot.get_guild(c_id) is None or not isinstance(self.bot.get_guild(c_id).get_channel(log_id), discord.TextChannel)):
            return await interaction.response.send_message("Server C or its log channel ID is invalid.", ephemeral=True)
        if not c_id and log_id:
            return await interaction.response.send_message("Provide Server C ID when setting a log channel.", ephemeral=True)
        await database.set_config(guild.id, server_a_id=guild.id, server_b_id=b_id,
            server_c_id=c_id, mentorship_role_id=role_id, sales_channel_id=sales_id,
            role_assigned_channel_id=assigned_id, role_revoked_channel_id=revoked_id,
            ticket_category_id=ticket_cat_id, renewal_category_id=renewal_cat_id,
            monthly_url=monthly_url, quarterly_url=quarterly_url, staff_role_id=staff_id,
            log_channel_id=log_id)
        await interaction.response.send_message("Configuration saved. Monthly and Quarterly checkout links are active.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Config(bot))
