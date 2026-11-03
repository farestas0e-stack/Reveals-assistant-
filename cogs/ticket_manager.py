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
        labels = {
            "mentorship:ticket:support": await self.bot.database.get_setting("panel_button_support"),
            "mentorship:ticket:purchase": await self.bot.database.get_setting("panel_button_purchase"),
            "mentorship:ticket:renewal": await self.bot.database.get_setting("panel_button_renewal"),
        }
        for child in self.panel_view.children:
            if isinstance(child, discord.ui.Button) and labels.get(child.custom_id):
                child.label = labels[child.custom_id]

    def _in_server_a(self, interaction: discord.Interaction) -> bool:
        return interaction.guild is not None and interaction.guild.id == config.SERVER_A_ID

    async def _setting_int(self, key: str, fallback: int = 0) -> int:
        value = await self.bot.database.get_setting(key)
        try:
            return int(value) if value else fallback
        except ValueError:
            return fallback

    async def _staff_role(self, guild: discord.Guild) -> discord.Role | None:
        role_id = await self._setting_int("staff_role_id", config.MODERATOR_ROLE_ID)
        return guild.get_role(role_id) if role_id else None

    async def _assign_server_b_access_role(self, member: discord.Member) -> bool:
        role_value = await self.bot.database.get_setting("server_b_access_role_id")
        if not role_value:
            return True
        try:
            role_id = int(role_value)
        except ValueError:
            log.error("Configured Server B access role ID is invalid.")
            return False
        role = member.guild.get_role(role_id)
        bot_member = member.guild.me
        if role is None or role.managed or bot_member is None:
            log.error("Configured Server B access role or bot member is unavailable.")
            return False
        if not bot_member.guild_permissions.manage_roles or role >= bot_member.top_role:
            log.error("Bot cannot assign Server B access role %s; check Manage Roles and role hierarchy.", role_id)
            return False
        if role not in member.roles:
            try:
                await member.add_roles(role, reason="Verified Mentorship membership in Server A")
            except (discord.Forbidden, discord.HTTPException):
                log.exception("Could not assign Server B access role to %s", member.id)
                return False
        return True

    async def create_private_ticket(
        self, guild: discord.Guild, user: discord.Member, ticket_type: str,
        *, opening_message: str | None = None,
    ) -> discord.TextChannel:
        staff_role = await self._staff_role(guild)
        if staff_role is None:
            raise RuntimeError("Staff role is not configured. An administrator must run /setstaffrole first.")
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
            if not categories:
                name = "Tickets"
            else:
                part_numbers = [
                    int(item.name.rsplit(" ", 1)[-1])
                    for item in categories if item.name != "Tickets"
                ]
                name = f"Tickets - Part {max(part_numbers, default=1) + 1}"
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
        existing = await self.bot.database.get_open_ticket_for_user(
            interaction.guild.id, interaction.user.id
        )
        if existing:
            channel = interaction.guild.get_channel(existing["channel_id"])
            if channel:
                await interaction.response.send_message(
                    f"You already have an open ticket: {channel.mention}", ephemeral=True
                )
                return

        await interaction.response.defer(ephemeral=True, thinking=True)
        if ticket_type in {"purchase", "renewal"}:
            setting_key = (
                "superprofile_checkout_url" if ticket_type == "purchase"
                else "superprofile_renewal_url"
            )
            payment_url = await self.bot.database.get_setting(setting_key)
            if not payment_url:
                await interaction.followup.send(
                    "The payment link has not been configured yet. Please contact an administrator.",
                    ephemeral=True,
                )
                return
            try:
                await interaction.user.send(
                    f"Your {ticket_type} link is ready: {payment_url}"
                )
                await interaction.followup.send(
                    "I've sent your payment link by DM.", ephemeral=True
                )
                return
            except discord.HTTPException:
                # A private ticket is the fallback when the member cannot receive DMs.
                pass

        try:
            opening = None
            if ticket_type in {"purchase", "renewal"}:
                key = ("superprofile_checkout_url" if ticket_type == "purchase"
                       else "superprofile_renewal_url")
                payment_url = await self.bot.database.get_setting(key)
                if payment_url:
                    opening = (
                        f"Hello {interaction.user.mention}. I couldn't send the payment link "
                        f"by DM, so here it is in your private ticket:\n{payment_url}"
                    )
            channel = await self.create_private_ticket(
                interaction.guild, interaction.user, ticket_type,
                opening_message=opening,
            )
            await interaction.followup.send(
                f"Your private ticket is ready: {channel.mention}", ephemeral=True
            )
        except (discord.Forbidden, discord.HTTPException, RuntimeError) as exc:
            log.exception("Could not create ticket")
            await interaction.followup.send(
                f"I couldn't create your ticket. Please contact staff. ({type(exc).__name__})",
                ephemeral=True,
            )

    async def _create_invitation_fallback(
        self, member: discord.Member, message: str
    ) -> bool:
        guild_a = self.bot.get_guild(config.SERVER_A_ID)
        if guild_a is None:
            return False
        member_a = guild_a.get_member(member.id)
        if member_a is None:
            try:
                member_a = await guild_a.fetch_member(member.id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return False

        existing = await self.bot.database.get_open_tickets_for_user(guild_a.id, member.id)
        existing_invite = next(
            (ticket for ticket in existing if ticket["ticket_type"] == "invitation"), None
        )
        if existing_invite:
            channel = guild_a.get_channel(existing_invite["channel_id"])
            if channel:
                try:
                    await channel.send(message)
                    return True
                except discord.HTTPException:
                    log.exception("Could not update invitation ticket %s", channel.id)
                    return False

        try:
            ticket = await self.create_private_ticket(
                guild_a, member_a, "invitation", opening_message=message
            )
            log.info("Created invitation ticket %s for %s", ticket.id, member.id)
            return True
        except (discord.Forbidden, discord.HTTPException, RuntimeError):
            log.exception("Could not create invitation fallback ticket for %s", member.id)
            return False

    async def send_server_b_invite(self, member: discord.Member) -> bool:
        """Send a one-use invite, or create a private invitation ticket on any delivery failure."""
        if not any(role.id == config.MENTORSHIP_ROLE_ID for role in member.roles):
            log.warning("Refusing to create an invite for %s without the Mentorship role.", member.id)
            return False

        guild_b = self.bot.get_guild(config.SERVER_B_ID)
        if guild_b is None:
            return await self._create_invitation_fallback(
                member,
                "Your membership is active, but I could not reach the private community server "
                "to generate an invitation. Staff will help you shortly.",
            )

        member_b = guild_b.get_member(member.id)
        if member_b is None:
            try:
                member_b = await guild_b.fetch_member(member.id)
            except discord.NotFound:
                member_b = None
            except (discord.Forbidden, discord.HTTPException):
                log.exception("Could not check whether %s is already in Server B", member.id)
                return await self._create_invitation_fallback(
                    member, "I could not verify your private community membership. Staff will help you."
                )
        if member_b is not None:
            if not await self._assign_server_b_access_role(member_b):
                return await self._create_invitation_fallback(
                    member,
                    "You are already in Server B, but I could not grant the configured access role. "
                    "Staff will help you shortly.",
                )
            guild_a = self.bot.get_guild(config.SERVER_A_ID)
            if guild_a:
                tickets = await self.bot.database.get_open_tickets_for_user(guild_a.id, member.id)
                for ticket in tickets:
                    if ticket["ticket_type"] in {"purchase", "invitation", "renewal"}:
                        ticket_channel = guild_a.get_channel(ticket["channel_id"])
                        await self.bot.database.close_ticket(ticket["channel_id"])
                        if ticket_channel:
                            try:
                                await ticket_channel.delete(reason="Member already has verified Server B access")
                            except discord.HTTPException:
                                log.exception("Could not delete completed onboarding ticket %s", ticket_channel.id)
            log.info("Member %s is already in Server B; no invite is needed.", member.id)
            return True

        target_channel = None
        configured_channel = await self.bot.database.get_setting("server_b_invite_channel_id")
        if configured_channel:
            try:
                selected = guild_b.get_channel(int(configured_channel))
            except ValueError:
                selected = None
            if isinstance(selected, discord.TextChannel):
                selected_perms = selected.permissions_for(guild_b.me)
                if selected_perms.create_instant_invite and selected_perms.view_channel:
                    target_channel = selected
        if target_channel is None:
            for channel in guild_b.text_channels:
                perms = channel.permissions_for(guild_b.me)
                if perms.create_instant_invite and perms.view_channel:
                    target_channel = channel
                    break

        if target_channel is None:
            return await self._create_invitation_fallback(
                member,
                "Your membership is active, but I could not find a Server B channel where I can "
                "create an invitation. Staff will configure access and help you.",
            )

        try:
            invite = await target_channel.create_invite(
                max_age=0, max_uses=1, temporary=False,
                unique=True, reason=f"One-use membership invite for {member.id}"
            )
        except (discord.Forbidden, discord.HTTPException):
            log.exception("Invite creation failed for %s", member.id)
            return await self._create_invitation_fallback(
                member,
                "Your membership is active, but Discord did not let me generate an invitation. "
                "Staff will help you shortly.",
            )

        try:
            await member.send(
                f"Your private community invitation is ready: {invite.url}\n"
                "This invitation can be used once and does not expire by time."
            )
            return True
        except discord.HTTPException:
            return await self._create_invitation_fallback(
                member,
                f"Hello <@{member.id}>. I could not send the invitation by DM. "
                f"Use this private invitation instead: {invite.url}\n"
                "This ticket will be deleted automatically after you join Server B.",
            )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.guild.id != config.SERVER_B_ID or member.bot:
            return
        guild_a = self.bot.get_guild(config.SERVER_A_ID)
        if guild_a is None:
            return
        member_a = guild_a.get_member(member.id)
        if member_a is None:
            try:
                member_a = await guild_a.fetch_member(member.id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                member_a = None
        eligible = bool(member_a and any(
            role.id == config.MENTORSHIP_ROLE_ID for role in member_a.roles
        ))
        if not eligible:
            try:
                await member.kick(reason="Server B access requires the Mentorship role in Server A")
            except (discord.Forbidden, discord.HTTPException):
                log.exception("Could not remove ineligible joiner %s from Server B", member.id)
            return
        if not await self._assign_server_b_access_role(member):
            await self._create_invitation_fallback(
                member,
                "You joined Server B, but I could not grant the configured access role. "
                "Please wait for staff to finish your access setup.",
            )
            return
        tickets = await self.bot.database.get_open_tickets_for_user(guild_a.id, member.id)
        for ticket in tickets:
            if ticket["ticket_type"] in {"purchase", "invitation", "renewal"}:
                channel = guild_a.get_channel(ticket["channel_id"])
                await self.bot.database.close_ticket(ticket["channel_id"])
                if channel:
                    try:
                        await channel.delete(reason="Eligible ticket creator successfully joined Server B")
                    except discord.HTTPException:
                        log.exception("Could not delete completed onboarding ticket %s", channel.id)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if after.guild.id != config.SERVER_B_ID or after.bot:
            return
        role_value = await self.bot.database.get_setting("server_b_access_role_id")
        if not role_value:
            return
        try:
            access_role_id = int(role_value)
        except ValueError:
            return
        had_access = any(role.id == access_role_id for role in before.roles)
        has_access = any(role.id == access_role_id for role in after.roles)
        if had_access or not has_access:
            return

        guild_a = self.bot.get_guild(config.SERVER_A_ID)
        if guild_a is None:
            return
        member_a = guild_a.get_member(after.id)
        if member_a is None:
            try:
                member_a = await guild_a.fetch_member(after.id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                member_a = None
        if not member_a or not any(
            role.id == config.MENTORSHIP_ROLE_ID for role in member_a.roles
        ):
            return

        tickets = await self.bot.database.get_open_tickets_for_user(guild_a.id, after.id)
        for ticket in tickets:
            if ticket["ticket_type"] in {"purchase", "invitation", "renewal"}:
                channel = guild_a.get_channel(ticket["channel_id"])
                await self.bot.database.close_ticket(ticket["channel_id"])
                if channel:
                    try:
                        await channel.delete(reason="Eligible member access role granted in Server B")
                    except discord.HTTPException:
                        log.exception("Could not delete completed onboarding ticket %s", channel.id)

    @app_commands.command(name="createpanel", description="Create the persistent support and purchase panel.")
    @app_commands.checks.has_permissions(administrator=True)
    async def createpanel(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or interaction.guild.id != config.SERVER_A_ID:
            await interaction.response.send_message("Use this command in Server A.", ephemeral=True)
            return
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("Run this command in a normal text channel.", ephemeral=True)
            return
        saved_channel = await self.bot.database.get_setting("panel_channel_id")
        saved_message = await self.bot.database.get_setting("panel_message_id")
        if saved_channel and saved_message:
            existing_channel = self.bot.get_channel(int(saved_channel))
            if isinstance(existing_channel, discord.TextChannel):
                try:
                    await existing_channel.fetch_message(int(saved_message))
                    await interaction.response.send_message(
                        "A panel is already saved. Use /editpanel or /refreshpanel, "
                        "or /deletepanel before creating another.",
                        ephemeral=True,
                    )
                    return
                except discord.NotFound:
                    pass
                except (discord.Forbidden, discord.HTTPException):
                    await interaction.response.send_message(
                        "I couldn't check the existing panel. Check my channel permissions.",
                        ephemeral=True,
                    )
                    return
        embed = discord.Embed(
            title="Member Help Desk",
            description="Choose an option below to open a private ticket.",
            color=discord.Color.blurple()
        )
        message = await interaction.channel.send(embed=embed, view=self.panel_view)
        await self.bot.database.set_setting("panel_channel_id", str(message.channel.id))
        await self.bot.database.set_setting("panel_message_id", str(message.id))
        await interaction.response.send_message("The persistent ticket panel has been posted.", ephemeral=True)

    @app_commands.command(name="editpanel", description="Edit the saved panel title, description and color.")
    @app_commands.checks.has_permissions(administrator=True)
    async def editpanel(
        self, interaction: discord.Interaction, title: str | None = None,
        description: str | None = None, color: str | None = None
    ) -> None:
        if not self._in_server_a(interaction):
            await interaction.response.send_message("Use this command in Server A.", ephemeral=True)
            return
        channel_id = await self.bot.database.get_setting("panel_channel_id")
        message_id = await self.bot.database.get_setting("panel_message_id")
        if not channel_id or not message_id:
            await interaction.response.send_message("Create a panel first with /createpanel.", ephemeral=True)
            return
        channel = self.bot.get_channel(int(channel_id))
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("The saved panel channel is unavailable.", ephemeral=True)
            return
        try:
            message = await channel.fetch_message(int(message_id))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            await interaction.response.send_message("I couldn't find the saved panel message.", ephemeral=True)
            return
        embed = message.embeds[0].copy() if message.embeds else discord.Embed()
        if title is not None:
            embed.title = title[:256]
        if description is not None:
            embed.description = description[:4000]
        if color is not None:
            try:
                cleaned = color.strip().removeprefix("#")
                if len(cleaned) not in (6,):
                    raise ValueError
                embed.color = discord.Color(int(cleaned, 16))
            except ValueError:
                await interaction.response.send_message("Color must be a hex value such as #5865F2.", ephemeral=True)
                return
        await message.edit(embed=embed, view=self.panel_view)
        await interaction.response.send_message("Panel updated.", ephemeral=True)

    async def _edit_saved_embed(self, interaction: discord.Interaction, *, title: str | None = None,
                                description: str | None = None, color: str | None = None) -> None:
        if not self._in_server_a(interaction):
            await interaction.response.send_message("Use this command in Server A.", ephemeral=True)
            return
        channel_id = await self.bot.database.get_setting("panel_channel_id")
        message_id = await self.bot.database.get_setting("panel_message_id")
        if not channel_id or not message_id:
            await interaction.response.send_message("Create a panel first with /createpanel.", ephemeral=True)
            return
        channel = self.bot.get_channel(int(channel_id))
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("The saved panel channel is unavailable.", ephemeral=True)
            return
        try:
            message = await channel.fetch_message(int(message_id))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            await interaction.response.send_message("I couldn't find the saved panel message.", ephemeral=True)
            return
        embed = message.embeds[0].copy() if message.embeds else discord.Embed()
        if title is not None:
            embed.title = title[:256]
        if description is not None:
            embed.description = description[:4000]
        if color is not None:
            try:
                cleaned = color.strip().removeprefix("#")
                if len(cleaned) != 6:
                    raise ValueError
                embed.color = discord.Color(int(cleaned, 16))
            except ValueError:
                await interaction.response.send_message("Color must be a hex value such as #5865F2.", ephemeral=True)
                return
        await message.edit(embed=embed, view=self.panel_view)
        await interaction.response.send_message("Panel updated.", ephemeral=True)

    @app_commands.command(name="settitle", description="Change the saved panel title.")
    @app_commands.checks.has_permissions(administrator=True)
    async def settitle(self, interaction: discord.Interaction, title: str) -> None:
        await self._edit_saved_embed(interaction, title=title)

    @app_commands.command(name="setdescription", description="Change the saved panel description.")
    @app_commands.checks.has_permissions(administrator=True)
    async def setdescription(self, interaction: discord.Interaction, description: str) -> None:
        await self._edit_saved_embed(interaction, description=description)

    @app_commands.command(name="setcolor", description="Change the saved panel embed color.")
    @app_commands.checks.has_permissions(administrator=True)
    async def setcolor(self, interaction: discord.Interaction, hex_color: str) -> None:
        await self._edit_saved_embed(interaction, color=hex_color)

    @app_commands.command(name="setbutton", description="Change a ticket panel button label.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.choices(button=[
        app_commands.Choice(name="Support", value="support"),
        app_commands.Choice(name="Purchase", value="purchase"),
        app_commands.Choice(name="Renewal", value="renewal"),
    ])
    async def setbutton(
        self, interaction: discord.Interaction,
        button: app_commands.Choice[str], label: str
    ) -> None:
        if not self._in_server_a(interaction):
            await interaction.response.send_message("Use this command in Server A.", ephemeral=True)
            return
        label = label.strip()
        if not label or len(label) > 80:
            await interaction.response.send_message("Button labels must contain 1–80 characters.", ephemeral=True)
            return
        await self.bot.database.set_setting(f"panel_button_{button.value}", label)
        custom_id = f"mentorship:ticket:{button.value}"
        for child in self.panel_view.children:
            if isinstance(child, discord.ui.Button) and child.custom_id == custom_id:
                child.label = label
        await interaction.response.send_message(
            f"The {button.name} button label is now **{label}**. Use /refreshpanel to update the posted panel.",
            ephemeral=True,
        )

    @app_commands.command(name="refreshpanel", description="Refresh the saved panel buttons and appearance.")
    @app_commands.checks.has_permissions(administrator=True)
    async def refreshpanel(self, interaction: discord.Interaction) -> None:
        if not self._in_server_a(interaction):
            await interaction.response.send_message("Use this command in Server A.", ephemeral=True)
            return
        channel_id = await self.bot.database.get_setting("panel_channel_id")
        message_id = await self.bot.database.get_setting("panel_message_id")
        if not channel_id or not message_id:
            await interaction.response.send_message("Create a panel first with /createpanel.", ephemeral=True)
            return
        channel = self.bot.get_channel(int(channel_id))
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("The saved panel channel is unavailable.", ephemeral=True)
            return
        try:
            message = await channel.fetch_message(int(message_id))
            await message.edit(view=self.panel_view)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            await interaction.response.send_message("I couldn't refresh the saved panel.", ephemeral=True)
            return
        await interaction.response.send_message("Panel refreshed.", ephemeral=True)

    @app_commands.command(name="closeticket", description="Close and delete the current ticket (staff/admin).")
    async def closeticket(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or interaction.guild.id != config.SERVER_A_ID:
            await interaction.response.send_message("Use this command in Server A.", ephemeral=True)
            return
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("Use this inside a ticket channel.", ephemeral=True)
            return
        cursor = await self.bot.database._db().execute(
            "SELECT ticket_id FROM tickets WHERE channel_id=? AND status='open'",
            (interaction.channel.id,),
        )
        ticket_row = await cursor.fetchone()
        await cursor.close()
        if not ticket_row:
            await interaction.response.send_message("This channel is not an open bot ticket.", ephemeral=True)
            return
        staff_id = await self._setting_int("staff_role_id", config.MODERATOR_ROLE_ID)
        is_staff = isinstance(interaction.user, discord.Member) and (
            interaction.user.guild_permissions.administrator or
            (staff_id and any(role.id == staff_id for role in interaction.user.roles))
        )
        if not is_staff:
            await interaction.response.send_message("Only configured staff can use this command.", ephemeral=True)
            return
        channel = interaction.channel
        await self.bot.database.close_ticket(channel.id)
        await interaction.response.send_message("Ticket closed. Deleting this channel.", ephemeral=True)
        await channel.delete(reason=f"Ticket closed by staff member {interaction.user.id}")

    @app_commands.command(name="deletepanel", description="Delete the saved ticket panel.")
    @app_commands.checks.has_permissions(administrator=True)
    async def deletepanel(self, interaction: discord.Interaction) -> None:
        if not self._in_server_a(interaction):
            await interaction.response.send_message("Use this command in Server A.", ephemeral=True)
            return
        channel_id = await self.bot.database.get_setting("panel_channel_id")
        message_id = await self.bot.database.get_setting("panel_message_id")
        if not channel_id or not message_id:
            await interaction.response.send_message("No saved panel was found.", ephemeral=True)
            return
        channel = self.bot.get_channel(int(channel_id))
        if isinstance(channel, discord.TextChannel):
            try:
                message = await channel.fetch_message(int(message_id))
                await message.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
        await self.bot.database.set_setting("panel_channel_id", "")
        await self.bot.database.set_setting("panel_message_id", "")
        await interaction.response.send_message("Saved panel deleted (if it still existed).", ephemeral=True)

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
