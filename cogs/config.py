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
        ticket_log_channel_id="Optional ticket transcript and closure log channel ID in Server A",
        trusted_provider_manager_role_id="Role allowed to confirm provider-approved payouts",
        sales_staff_role_id="Sales staff role allowed to confirm approved payouts",
        community_mentorship_role_id="Mentorship access role in Server B"
    )
    async def setup(
        self, interaction: discord.Interaction, server_b_id: str,
        mentorship_role_id: str, sales_channel_id: str,
        role_assigned_channel_id: str, role_revoked_channel_id: str,
        ticket_category_id: str, renewal_category_id: str,
        renewal_url: str,
        staff_role_id: str | None = None, ticket_log_channel_id: str | None = None,
        trusted_provider_manager_role_id: str | None = None, sales_staff_role_id: str | None = None,
        community_mentorship_role_id: str | None = None
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
            ticket_log_id = int(ticket_log_channel_id) if ticket_log_channel_id else None
            provider_manager_id = int(trusted_provider_manager_role_id) if trusted_provider_manager_role_id else None
            sales_staff_id = int(sales_staff_role_id) if sales_staff_role_id else None
            community_role_id = int(community_mentorship_role_id) if community_mentorship_role_id else None
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
        if sales_id in (assigned_id, revoked_id) or assigned_id == revoked_id:
            return await interaction.response.send_message(
                "Use three separate channels: sales (screenshots only), role assigned, and role revoked.",
                ephemeral=True
            )
        if not isinstance(ticket_category, discord.CategoryChannel) or not isinstance(renewal_category, discord.CategoryChannel):
            return await interaction.response.send_message("Ticket category IDs must identify categories in Server A.", ephemeral=True)
        ticket_log = guild.get_channel(ticket_log_id) if ticket_log_id else None
        if ticket_log_id and not isinstance(ticket_log, discord.TextChannel):
            return await interaction.response.send_message("Ticket log channel ID must identify a text channel in Server A.", ephemeral=True)
        if staff_id and guild.get_role(staff_id) is None:
            return await interaction.response.send_message("Staff role ID is invalid.", ephemeral=True)
        if provider_manager_id and guild.get_role(provider_manager_id) is None:
            return await interaction.response.send_message("Trusted Provider Manager role ID is invalid.", ephemeral=True)
        if sales_staff_id and guild.get_role(sales_staff_id) is None:
            return await interaction.response.send_message("Sales Staff role ID is invalid.", ephemeral=True)
        if not provider_manager_id or not sales_staff_id:
            return await interaction.response.send_message("Configure both Trusted Provider Manager and Sales Staff roles.", ephemeral=True)
        if not community_role_id:
            return await interaction.response.send_message("Configure the Server B mentorship role.", ephemeral=True)
        if guild.me is None:
            return await interaction.response.send_message("Bot member cache is unavailable; retry in a moment.", ephemeral=True)
        if role >= guild.me.top_role:
            return await interaction.response.send_message(
                "Move the bot's highest role above the mentorship role before setup.", ephemeral=True
            )
        if not guild.me.guild_permissions.manage_roles or not guild.me.guild_permissions.manage_channels or not guild.me.guild_permissions.view_audit_log:
            return await interaction.response.send_message(
                "The bot needs Manage Roles, Manage Channels, and View Audit Log in Server A to verify trusted role assignments.", ephemeral=True
            )
        community = self.bot.get_guild(b_id)
        if community is None or community.me is None:
            return await interaction.response.send_message("Invite the bot to Server B first.", ephemeral=True)
        if community_role_id and community.get_role(community_role_id) is None:
            return await interaction.response.send_message("Server B mentorship role ID is invalid.", ephemeral=True)
        if community_role_id and community.me.top_role <= community.get_role(community_role_id):
            return await interaction.response.send_message("Move the bot role above the Server B mentorship role.", ephemeral=True)
        if (not community.me.guild_permissions.kick_members or
                not community.me.guild_permissions.create_instant_invite or
                not community.me.guild_permissions.manage_guild or
                (community_role_id and not community.me.guild_permissions.manage_roles)):
            return await interaction.response.send_message(
                "The bot needs Kick Members, Create Invite, Manage Server (to track invite use), and Manage Roles in Server B.", ephemeral=True
            )
        await database.set_config(
            guild.id, server_a_id=guild.id, server_b_id=b_id,
            mentorship_role_id=role_id, sales_channel_id=sales_id,
            role_assigned_channel_id=assigned_id, role_revoked_channel_id=revoked_id,
            ticket_category_id=ticket_cat_id, renewal_category_id=renewal_cat_id,
            monthly_url=renewal_url.strip(), renewal_url=renewal_url.strip(),
            staff_role_id=staff_id,
            ticket_log_channel_id=ticket_log_id,
            trusted_provider_manager_role_id=provider_manager_id,
            sales_staff_role_id=sales_staff_id
        )
        await interaction.response.send_message(
            "Configuration saved. Membership role assignment triggers automatic payment verification and Server B access.",
            ephemeral=True
        )

    @app_commands.command(name="set_ticket_log", description="Set the channel for ticket closure logs and transcripts.")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_ticket_log(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if interaction.guild is None:
            return await interaction.response.send_message("Run this command inside Server A.", ephemeral=True)
        await database.set_config(interaction.guild.id, ticket_log_channel_id=channel.id)
        embed = discord.Embed(
            title="Ticket transcript logging configured",
            description=f"Ticket closure logs and transcript files will be sent to {channel.mention}.",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

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
        embed.add_field(name="Trusted Provider Manager", value=f"<@&{cfg['trusted_provider_manager_role_id']}>" if cfg.get("trusted_provider_manager_role_id") else "Not set", inline=True)
        embed.add_field(name="Sales Staff", value=f"<@&{cfg['sales_staff_role_id']}>" if cfg.get("sales_staff_role_id") else "Not set", inline=True)
        embed.add_field(name="Server B mentorship role", value=f"<@&{cfg['community_mentorship_role_id']}>" if cfg.get("community_mentorship_role_id") else "Not set", inline=True)
        embed.add_field(name="Staff role", value=f"<@&{cfg['staff_role_id']}>" if cfg.get("staff_role_id") else "Not set", inline=True)
        embed.add_field(name="Ticket logs / transcripts", value=f"<#{cfg['ticket_log_channel_id']}>" if cfg.get("ticket_log_channel_id") else "Not set — configure in /setup", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Config(bot))
