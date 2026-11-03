from __future__ import annotations

import logging
import re

import discord
from discord import app_commands
from discord.ext import commands

import config

log = logging.getLogger(__name__)


class TicketPanelView(discord.ui.View):
    """Persistent public panel. Its buttons create private tickets in Server A."""

    def __init__(self, cog: "TicketManager") -> None:
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Support", style=discord.ButtonStyle.primary,
                       custom_id="mentorship:ticket:support", emoji="🎫")
    async def support(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.cog.panel_ticket(interaction, "support")

    @discord.ui.button(label="Purchase", style=discord.ButtonStyle.success,
                       custom_id="mentorship:ticket:purchase", emoji="🛒")
    async def purchase(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.cog.panel_ticket(interaction, "purchase")

    @discord.ui.button(label="Renewal", style=discord.ButtonStyle.secondary,
                       custom_id="mentorship:ticket:renewal", emoji="🔄")
    async def renewal(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.cog.panel_ticket(interaction, "renewal")


class TicketManager(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.panel_view = TicketPanelView(self)

    async def cog_load(self) -> None:
        self.bot.add_view(self.panel_view)

    async def _setting_int(self, key: str, fallback: int = 0) -> int:
        value = await self.bot.database.get_setting(key)
        try:
            return int(value) if value else fallback
        except ValueError:
            return fallback

    async def _staff_role(self, guild: discord.Guild) -> discord.Role | None:
        role_id = await self._setting_int("staff_role_id", config.MODERATOR_ROLE_ID)
        return guild.get_role(role_id) if role_id else None

    async def create_private_ticket(
        self, guild: discord.Guild, user: discord.Member, ticket_type: str,
        *, opening_message: str | None = None,
    ) -> discord.TextChannel:
        staff_role = await self._staff_role(guild)
        bot_member = guild.me
        if bot_member is None:
            raise RuntimeError("The bot member could not be resolved in the server.")

        overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                               read_message_history=True, attach_files=True),
            bot_member: discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                                     manage_channels=True, read_message_history=True),
        }
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True,
                manage_channels=True
            )

        categories = sorted(
            [c for c in guild.categories if c.name == "Tickets" or
             re.fullmatch(r"Tickets - Part \d+", c.name)],
            key=lambda c: (0 if c.name == "Tickets" else int(c.name.rsplit(" ", 1)[-1]))
        )
        category = next((c for c in categories if len(c.channels) < 49), None)
        if category is None:
            name = "Tickets" if not categories else f"Tickets - Part {len(categories) + 1}"
            category = await guild.create_category(
                name, overwrites={guild.default_role: discord.PermissionOverwrite(view_channel=False)},
                reason="Automatic ticket category management"
            )

        safe_name = re.sub(r"[^a-z0-9-]", "-", user.display_name.lower()).strip("-")[:18] or "member"
        channel = await guild.create_text_channel(
            name=f"{ticket_type}-{safe_name}",
            category=category, overwrites=overwrites,
            topic=f"{ticket_type.title()} ticket for user {user.id}",
            reason=f"Create private {ticket_type} ticket"
        )
        await self.bot.database.create_ticket(guild.id, channel.id, user.id, ticket_type)
        message = opening_message or (
            f"Hello {user.mention}. Staff will assist you here. "
            "Please do not share passwords or payment card details."
        )
        await channel.send(message)
        return channel

    async def panel_ticket(self, interaction: discord.Interaction, ticket_type: str) -> None:
        if interaction.guild is None or interaction.guild.id != config.SERVER_A_ID:
            await interaction.response.send_message(
                "Please use this panel in the Hub server.", ephemeral=True)
            return
        existing = await self.bot.database.get_open_ticket_for_user(interaction.guild.id,
                                                                      interaction.user.id)
        if existing:
            channel = interaction.guild.get_channel(existing["channel_id"])
            if channel:
                await interaction.response.send_message(
                    f"You already have an open ticket: {channel.mention}", ephemeral=True)
                return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            channel = await self.create_private_ticket(
                interaction.guild, interaction.user, ticket_type
            )
            await interaction.followup.send(f"Your private ticket is ready: {channel.mention}",
                                            ephemeral=True)
        except (discord.Forbidden, discord.HTTPException, RuntimeError) as exc:
            log.exception("Could not create ticket")
            await interaction.followup.send(
                f"I couldn't create your ticket. Please contact staff. ({type(exc).__name__})",
                ephemeral=True)

    async def send_server_b_invite(self, member: discord.Member) -> bool:
        """Send a fresh single-use invite; create a private invitation ticket if DM fails."""
        guild_b = self.bot.get_guild(config.SERVER_B_ID)
        if guild_b is None:
            log.error("Server B is not available to the bot.")
            return False
        target_channel = None
        for channel in guild_b.text_channels:
            perms = channel.permissions_for(guild_b.me)
            if perms.create_instant_invite and perms.view_channel:
                target_channel = channel
                break
        if target_channel is None:
            log.error("No Server B channel permits invite creation.")
            return False
        try:
            invite = await target_channel.create_invite(
                max_age=0, max_uses=1, temporary=False,
                unique=True, reason=f"One-use membership invite for {member.id}"
            )
        except (discord.Forbidden, discord.HTTPException):
            log.exception("Invite creation failed")
            return False

        try:
            await member.send(
                f"Your private community invitation is ready: {invite.url}\n"
                "This invitation can be used once and does not expire by time."
            )
            return True
        except discord.Forbidden:
            guild_a = self.bot.get_guild(config.SERVER_A_ID)
            if guild_a is None:
                return False
            existing = await self.bot.database.get_open_tickets_for_user(guild_a.id, member.id)
            if any(t["ticket_type"] == "invitation" for t in existing):
                return False
            try:
                ticket = await self.create_private_ticket(
                    guild_a, guild_a.get_member(member.id) or await guild_a.fetch_member(member.id),
                    "invitation",
                    opening_message=(
                        f"Hello <@{member.id}>. Your Server B invitation is below.\n"
                        f"{invite.url}\n\nThis private ticket will be deleted automatically "
                        "after you join the private community."
                    )
                )
                log.info("Created invitation ticket %s for %s", ticket.id, member.id)
                return True
            except (discord.Forbidden, discord.HTTPException, discord.NotFound):
                log.exception("Could not create invitation fallback ticket")
                return False

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.guild.id != config.SERVER_B_ID:
            return
        guild_a = self.bot.get_guild(config.SERVER_A_ID)
        if guild_a is None:
            return
        tickets = await self.bot.database.get_open_tickets_for_user(guild_a.id, member.id)
        for ticket in tickets:
            if ticket["ticket_type"] in {"invitation", "renewal"}:
                channel = guild_a.get_channel(ticket["channel_id"])
                await self.bot.database.close_ticket(ticket["channel_id"])
                if channel:
                    try:
                        await channel.delete(reason="Ticket creator successfully joined Server B")
                    except discord.HTTPException:
                        log.exception("Could not delete completed onboarding ticket %s", channel.id)

    @app_commands.command(name="createpanel", description="Create the persistent support and purchase panel.")
    @app_commands.checks.has_permissions(administrator=True)
    async def createpanel(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or interaction.guild.id != config.SERVER_A_ID:
            await interaction.response.send_message("Use this command in Server A.", ephemeral=True)
            return
        embed = discord.Embed(
            title="Member Help Desk",
            description="Choose an option below to open a private ticket.",
            color=discord.Color.blurple()
        )
        await interaction.channel.send(embed=embed, view=self.panel_view)
        await interaction.response.send_message("The persistent ticket panel has been posted.",
                                                ephemeral=True)

    @createpanel.error
    async def createpanel_error(self, interaction: discord.Interaction,
                                error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            message = "Only server administrators can create the panel."
        else:
            message = "I couldn't create the panel. Check my channel permissions."
            log.exception("createpanel failed", exc_info=error)
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TicketManager(bot))
