from urllib.parse import urlparse
import discord
from discord import app_commands
from discord.ext import commands
import database

def valid_url(value: str) -> bool:
    parsed = urlparse(value.strip())
    return parsed.scheme in ("https", "http") and bool(parsed.netloc)

class Config(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="setup", description="Configure Server A, Server B, tickets and checkout links.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        server_b_id="Server B numeric ID",
        mentorship_role_id="Mentorship/payment-verified role ID in Server A",
        sales_channel_id="Sales log channel ID in Server A",
        role_assigned_channel_id="Role assigned log channel ID in Server A",
        role_revoked_channel_id="Role revoked log channel ID in Server A",
        ticket_category_id="Purchase ticket category ID in Server A",
        renewal_category_id="Renewal ticket category ID in Server A",
        renewal_url="Single membership / renewal checkout URL",
        staff_role_id="Optional staff role ID in Server A",
        server_c_id="Optional moderation log server ID",
        log_channel_id="Optional moderation log channel ID in Server C"
    )
    async def setup(
        self, interaction: discord.Interaction, server_b_id: str,
        mentorship_role_id: str, sales_channel_id: str,
        role_assigned_channel_id: str, role_revoked_channel_id: str,
        ticket_category_id: str, renewal_category_id: str,
        renewal_url: str,
        staff_role_id: str | None = None, server_c_id: str | None = None,
        log_channel_id: str | None = None
    ):
        guild = interaction.guild
        if guild is None:
            return await interaction.response.send_message("Run /setup inside Server A.", ephemeral=True)
        try:
            b_id, role_id, sales_id, assigned_id, revoked_id, ticket_cat_id, renewal_cat_id = [
                int(value) for value in (
                    server_b_id, mentorship_role_id, sales_channel_id,
                    role_assigned_channel_id, role_revoked_channel_id,
                    ticket_category_id, renewal_category_id
                )
            ]
            staff_id = int(staff_role_id) if staff_role_id else None
            c_id = int(server_c_id) if server_c_id else None
            log_id = int(log_channel_id) if log_channel_id else None
        except ValueError:
            return await interaction.response.send_message("Every supplied ID must be numeric.", ephemeral=True)

        if not valid_url(renewal_url):
            return await interaction.response.send_message(
                "The membership / renewal link must be a valid http:// or https:// URL.", ephemeral=True
            )
        role = guild.get_role(role_id)
        sales = guild.get_channel(sales_id)
        assigned = guild.get_channel(assigned_id)
        revoked = guild.get_channel(revoked_id)
        ticket_category = guild.get_channel(ticket_cat_id)
        renewal_category = guild.get_channel(renewal_cat_id)
        if not isinstance(role, discord.Role):
            return await interaction.response.send_message("Mentorship role ID is invalid for Server A.", ephemeral=True)
        if not all(isinstance(channel, discord.TextChannel) for channel in (sales, assigned, revoked)):
            return await interaction.response.send_message("Sales/role log IDs must be text channels in Server A.", ephemeral=True)
        if not isinstance(ticket_category, discord.CategoryChannel) or not isinstance(renewal_category, discord.CategoryChannel):
            return await interaction.response.send_message("Ticket category IDs must identify categories in Server A.", ephemeral=True)
        if staff_id and guild.get_role(staff_id) is None:
            return await interaction.response.send_message("Staff role ID is invalid.", ephemeral=True)
        if guild.me is None:
            return await interaction.response.send_message("Bot member cache is unavailable; retry in a moment.", ephemeral=True)
        if role >= guild.me.top_role:
            return await interaction.response.send_message(
                "Move the bot's highest role above the mentorship role before setup.", ephemeral=True
            )
        if not guild.me.guild_permissions.manage_roles or not guild.me.guild_permissions.manage_channels:
            return await interaction.response.send_message(
                "The bot needs Manage Roles and Manage Channels in Server A.", ephemeral=True
            )
        community = self.bot.get_guild(b_id)
        if community is None or community.me is None:
            return await interaction.response.send_message("Invite the bot to Server B first.", ephemeral=True)
        if not community.me.guild_permissions.kick_members or not community.me.guild_permissions.create_instant_invite:
            return await interaction.response.send_message(
                "The bot needs Kick Members and Create Invite permissions in Server B.", ephemeral=True
            )
        if c_id is not None:
            audit_guild = self.bot.get_guild(c_id)
            audit_channel = audit_guild.get_channel(log_id) if audit_guild and log_id else None
            if not isinstance(audit_channel, discord.TextChannel):
                return await interaction.response.send_message(
                    "Server C and its text log channel must both be valid.", ephemeral=True
                )
        elif log_id is not None:
            return await interaction.response.send_message(
                "Provide Server C ID when configuring a Server C log channel.", ephemeral=True
            )

        await database.set_config(
            guild.id, server_a_id=guild.id, server_b_id=b_id, server_c_id=c_id,
            mentorship_role_id=role_id, sales_channel_id=sales_id,
            role_assigned_channel_id=assigned_id, role_revoked_channel_id=revoked_id,
            ticket_category_id=ticket_cat_id, renewal_category_id=renewal_cat_id,
            monthly_url=renewal_url.strip(), renewal_url=renewal_url.strip(),
            staff_role_id=staff_id,
            log_channel_id=log_id
        )
        await interaction.response.send_message(
            "Configuration saved. Single membership checkout, payment approval, role logs and Server B access are configured.",
            ephemeral=True
        )

    @app_commands.command(name="setup_status", description="Show the saved bot configuration.")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_status(self, interaction: discord.Interaction):
        cfg = await database.get_config(interaction.guild_id)
        if not cfg:
            return await interaction.response.send_message("No configuration saved. Run /setup.", ephemeral=True)
        embed = discord.Embed(title="Reveals Assistant configuration", color=discord.Color.blurple())
        embed.add_field(name="Server B", value=str(cfg.get("server_b_id") or "Missing"), inline=True)
        embed.add_field(name="Mentorship role", value=f"<@&{cfg['mentorship_role_id']}>" if cfg.get("mentorship_role_id") else "Missing", inline=True)
        for label, key in (
            ("Sales log", "sales_channel_id"),
            ("Role assigned log", "role_assigned_channel_id"),
            ("Role revoked log", "role_revoked_channel_id"),
            ("Purchase category", "ticket_category_id"),
            ("Renewal category", "renewal_category_id")
        ):
            value = f"<#{cfg[key]}>" if cfg.get(key) else "Missing"
            embed.add_field(name=label, value=value, inline=True)
        embed.add_field(name="Membership / renewal link", value="Configured" if (cfg.get("renewal_url") or cfg.get("monthly_url")) else "Missing", inline=True)
        embed.add_field(name="Staff role", value=f"<@&{cfg['staff_role_id']}>" if cfg.get("staff_role_id") else "Not set", inline=True)
        embed.add_field(name="Server C logs", value=f"Server {cfg.get('server_c_id')} / <#{cfg.get('log_channel_id')}>" if cfg.get("server_c_id") and cfg.get("log_channel_id") else "Not set", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Config(bot))
