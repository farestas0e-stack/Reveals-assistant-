from __future__ import annotations

import discord
import config
from discord import app_commands
from discord.ext import commands


class SetupCommands(commands.Cog):
    """Admin-only Discord commands for settings that should not require code edits."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="setup", description="Show the bot setup checklist.")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup(self, interaction: discord.Interaction) -> None:
        staff = await self.bot.database.get_setting("staff_role_id")
        checkout = await self.bot.database.get_setting("superprofile_checkout_url")
        renewal = await self.bot.database.get_setting("superprofile_renewal_url")
        moderation = await self.bot.database.get_setting("moderation_log_channel_id")
        invite_channel = await self.bot.database.get_setting("server_b_invite_channel_id")
        access_role = await self.bot.database.get_setting("server_b_access_role_id")
        embed = discord.Embed(
            title="Mentorship Bot Setup",
            description="Use the admin commands below to finish configuring the bot.",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Staff role", value="Configured" if staff else "Not configured", inline=True)
        embed.add_field(name="Checkout link", value="Configured" if checkout else "Not configured", inline=True)
        embed.add_field(name="Renewal link", value="Configured" if renewal else "Not configured", inline=True)
        embed.add_field(name="Moderation log channel", value="Configured" if moderation else "Not configured", inline=True)
        embed.add_field(name="Server B invite channel", value="Configured" if invite_channel else "Auto-detect", inline=True)
        embed.add_field(name="Server B access role", value="Configured" if access_role else "Not configured", inline=True)
        embed.add_field(
            name="Commands",
            value=(
                "• /setstaffrole — choose the staff role\n"
                "• /setlink — save your checkout or renewal URL\n"
                "• /setmembershipexpiry — record a member expiry\n"
                "• /syncmember — re-check role and resend invite\n"
                "• /recordrenewal — record renewal when the role stays assigned\n"
                "• /setmoderationchannel — choose the Server C log channel\n"
                "• /setinvitechannel — choose the Server B invite channel\n"
                "• /setcommunityrole — choose the Server B access role\n"
                "• /healthcheck — check permissions and server setup"
            ),
            inline=False,
        )
        embed.set_footer(text="Ticket categories are created and expanded automatically.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="setstaffrole", description="Set the role allowed to view private tickets.")
    @app_commands.checks.has_permissions(administrator=True)
    async def setstaffrole(self, interaction: discord.Interaction, role: discord.Role) -> None:
        if interaction.guild is None or interaction.guild.id != config.SERVER_A_ID:
            await interaction.response.send_message("Run this command in Server A.", ephemeral=True)
            return
        if role.is_default():
            await interaction.response.send_message("Choose a staff role other than @everyone.", ephemeral=True)
            return
        await self.bot.database.set_setting("staff_role_id", str(role.id))
        await interaction.response.send_message(
            f"Private tickets will be visible to {role.mention}, the ticket creator and the bot.",
            ephemeral=True,
        )

    async def _save_url(self, interaction: discord.Interaction, key: str, label: str, url: str) -> None:
        if interaction.guild is None or interaction.guild.id != config.SERVER_A_ID:
            await interaction.response.send_message("Run payment-link setup in Server A.", ephemeral=True)
            return
        cleaned = url.strip()
        if not cleaned.startswith("https://") or len(cleaned) > 500:
            await interaction.response.send_message(
                "Please provide a valid HTTPS link (starting with https://).", ephemeral=True
            )
            return
        await self.bot.database.set_setting(key, cleaned)
        await interaction.response.send_message(f"{label} link saved.", ephemeral=True)

    @app_commands.command(name="setcheckoutlink", description="Save your Superprofile purchase link.")
    @app_commands.checks.has_permissions(administrator=True)
    async def setcheckoutlink(self, interaction: discord.Interaction, url: str) -> None:
        await self._save_url(interaction, "superprofile_checkout_url", "Checkout", url)

    @app_commands.command(name="setrenewallink", description="Save your Superprofile renewal link.")
    @app_commands.checks.has_permissions(administrator=True)
    async def setrenewallink(self, interaction: discord.Interaction, url: str) -> None:
        await self._save_url(interaction, "superprofile_renewal_url", "Renewal", url)

    @app_commands.command(name="setlink", description="Set the checkout or renewal payment URL.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.choices(link_type=[
        app_commands.Choice(name="Purchase / checkout", value="checkout"),
        app_commands.Choice(name="Renewal", value="renewal"),
    ])
    async def setlink(
        self, interaction: discord.Interaction,
        link_type: app_commands.Choice[str], url: str
    ) -> None:
        key = "superprofile_checkout_url" if link_type.value == "checkout" else "superprofile_renewal_url"
        label = "Checkout" if link_type.value == "checkout" else "Renewal"
        await self._save_url(interaction, key, label, url)

    @app_commands.command(name="healthcheck", description="Check bot access and required permissions across all three servers.")
    @app_commands.checks.has_permissions(administrator=True)
    async def healthcheck(self, interaction: discord.Interaction) -> None:
        guild_a = self.bot.get_guild(config.SERVER_A_ID)
        guild_b = self.bot.get_guild(config.SERVER_B_ID)
        guild_c = self.bot.get_guild(config.SERVER_C_ID)
        checks: list[tuple[str, bool, str]] = []

        checks.append(("Server A connected", guild_a is not None,
                       "Hub server is reachable." if guild_a else "Bot is not in Server A."))
        checks.append(("Server B connected", guild_b is not None,
                       "Private server is reachable." if guild_b else "Bot is not in Server B."))
        checks.append(("Server C connected", guild_c is not None,
                       "Moderation server is reachable." if guild_c else "Bot is not in Server C."))

        if guild_a and guild_a.me:
            perms_a = guild_a.me.guild_permissions
            checks.append(("Server A Manage Channels", perms_a.manage_channels,
                           "Required to create/delete ticket channels."))
            checks.append(("Server A View Audit Log", perms_a.view_audit_log,
                           "Required to identify moderators and role-change actors."))
            staff_id = await self.bot.database.get_setting("staff_role_id")
            staff_role = guild_a.get_role(int(staff_id)) if staff_id and staff_id.isdigit() else None
            checks.append(("Staff role configured", staff_role is not None,
                           "Run /setstaffrole in Server A." if staff_role is None else staff_role.name))
            checks.append(("Mentorship role exists", guild_a.get_role(config.MENTORSHIP_ROLE_ID) is not None,
                           "The configured Mentorship role must exist in Server A."))
            for label, channel_id in (
                ("Sales notification channel", config.SALES_CHANNEL_ID),
                ("Role assigned notification channel", config.ROLE_ASSIGNED_CHANNEL_ID),
                ("Role removed notification channel", config.ROLE_REMOVED_CHANNEL_ID),
            ):
                notify_channel = guild_a.get_channel(channel_id)
                can_send = isinstance(notify_channel, discord.TextChannel) and (
                    notify_channel.permissions_for(guild_a.me).send_messages
                    and notify_channel.permissions_for(guild_a.me).embed_links
                )
                checks.append((label, can_send,
                               notify_channel.mention if can_send else "Check channel ID and Send Messages / Embed Links permissions."))
        if guild_b and guild_b.me:
            perms_b = guild_b.me.guild_permissions
            checks.append(("Server B Kick Members", perms_b.kick_members,
                           "Required to remove expired/ineligible members."))
            access_role_id = await self.bot.database.get_setting("server_b_access_role_id")
            if not access_role_id:
                checks.append(("Server B access role", True,
                               "Optional. Configure /setcommunityrole only if Server B channels require a member role."))
            else:
                access_role = guild_b.get_role(int(access_role_id)) if access_role_id.isdigit() else None
                can_assign_access = bool(
                    access_role and not access_role.managed and perms_b.manage_roles and access_role < guild_b.me.top_role
                )
                checks.append(("Server B access role", can_assign_access,
                               access_role.name if can_assign_access
                               else "Check /setcommunityrole, Manage Roles and role hierarchy."))
            invite_id = await self.bot.database.get_setting("server_b_invite_channel_id")
            invite_channel = guild_b.get_channel(int(invite_id)) if invite_id and invite_id.isdigit() else None
            if not isinstance(invite_channel, discord.TextChannel):
                invite_channel = next((channel for channel in guild_b.text_channels
                    if channel.permissions_for(guild_b.me).view_channel
                    and channel.permissions_for(guild_b.me).create_instant_invite), None)
            checks.append(("Server B invite channel", invite_channel is not None,
                           invite_channel.mention if invite_channel else "Set /setinvitechannel or grant Create Invite."))
        if guild_c and guild_c.me:
            log_id = await self.bot.database.get_setting("moderation_log_channel_id")
            log_channel = guild_c.get_channel(int(log_id)) if log_id and log_id.isdigit() else None
            can_log = isinstance(log_channel, discord.TextChannel) and (
                log_channel.permissions_for(guild_c.me).send_messages
                and log_channel.permissions_for(guild_c.me).embed_links
            )
            checks.append(("Server C moderation channel", can_log,
                           log_channel.mention if can_log
                           else "Run /setmoderationchannel and grant Send Messages / Embed Links."))
        checks.append(("Checkout link", bool(await self.bot.database.get_setting("superprofile_checkout_url")),
                       "Set with /setlink in Server A."))
        checks.append(("Renewal link", bool(await self.bot.database.get_setting("superprofile_renewal_url")),
                       "Set with /setlink in Server A."))

        embed = discord.Embed(title="Bot Health Check", color=discord.Color.blurple())
        for label, passed, detail in checks:
            embed.add_field(
                name=f"{'✅' if passed else '❌'} {label}",
                value=detail[:900],
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="setupstatus", description="Show whether the required settings are configured.")
    @app_commands.checks.has_permissions(administrator=True)
    async def setupstatus(self, interaction: discord.Interaction) -> None:
        values = {
            "Staff role": await self.bot.database.get_setting("staff_role_id"),
            "Superprofile checkout": await self.bot.database.get_setting("superprofile_checkout_url"),
            "Superprofile renewal": await self.bot.database.get_setting("superprofile_renewal_url"),
            "Server C moderation channel": await self.bot.database.get_setting("moderation_log_channel_id"),
            "Server B invite channel": await self.bot.database.get_setting("server_b_invite_channel_id"),
            "Server B access role": await self.bot.database.get_setting("server_b_access_role_id"),
        }
        lines = [f"**{name}:** {'Configured' if value else 'Not configured'}"
                 for name, value in values.items()]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @app_commands.command(name="setcommunityrole", description="Choose the Server B role granted to eligible Mentorship members.")
    @app_commands.checks.has_permissions(administrator=True)
    async def setcommunityrole(
        self, interaction: discord.Interaction, role: discord.Role
    ) -> None:
        if interaction.guild is None or interaction.guild.id != config.SERVER_B_ID:
            await interaction.response.send_message(
                "Run this command in Server B and select the private-community access role.",
                ephemeral=True,
            )
            return
        if role.is_default() or role.managed:
            await interaction.response.send_message(
                "Choose a normal, non-managed role other than @everyone.",
                ephemeral=True,
            )
            return
        bot_member = interaction.guild.me
        if bot_member is None or not bot_member.guild_permissions.manage_roles:
            await interaction.response.send_message(
                "I need Manage Roles in Server B before this role can be assigned.",
                ephemeral=True,
            )
            return
        if role >= bot_member.top_role:
            await interaction.response.send_message(
                "Move the bot's highest role above the selected community access role.",
                ephemeral=True,
            )
            return
        await self.bot.database.set_setting("server_b_access_role_id", str(role.id))
        await interaction.response.send_message(
            f"Eligible members will receive {role.mention} when they join Server B.",
            ephemeral=True,
        )

    @app_commands.command(name="setinvitechannel", description="Choose the Server B channel used to create member invitations.")
    @app_commands.checks.has_permissions(administrator=True)
    async def setinvitechannel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ) -> None:
        if interaction.guild is None or interaction.guild.id != config.SERVER_B_ID:
            await interaction.response.send_message(
                "Run this command in Server B and select a channel where the bot can create invites.",
                ephemeral=True,
            )
            return
        permissions = channel.permissions_for(interaction.guild.me)
        if not permissions.view_channel or not permissions.create_instant_invite:
            await interaction.response.send_message(
                "I need View Channel and Create Invite permissions in that channel.",
                ephemeral=True,
            )
            return
        await self.bot.database.set_setting("server_b_invite_channel_id", str(channel.id))
        await interaction.response.send_message(
            f"New member invitations will be created in {channel.mention}.",
            ephemeral=True,
        )

    @app_commands.command(name="setmoderationchannel", description="Choose the moderation log channel in Server C.")
    @app_commands.checks.has_permissions(administrator=True)
    async def setmoderationchannel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ) -> None:
        if interaction.guild is None or interaction.guild.id != config.SERVER_C_ID:
            await interaction.response.send_message(
                "Run this command in Server C, then select its moderation log channel.",
                ephemeral=True,
            )
            return
        permissions = channel.permissions_for(interaction.guild.me)
        if not permissions.view_channel or not permissions.send_messages or not permissions.embed_links:
            await interaction.response.send_message(
                "I need View Channel, Send Messages and Embed Links in that log channel.",
                ephemeral=True,
            )
            return
        await self.bot.database.set_setting("moderation_log_channel_id", str(channel.id))
        await interaction.response.send_message(
            f"Moderation events will be forwarded to {channel.mention}.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SetupCommands(bot))
