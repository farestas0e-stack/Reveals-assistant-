from __future__ import annotations

import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config

log = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_expiry(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Include a timezone, e.g. 2027-01-31T23:59:00+00:00.")
    return parsed.astimezone(timezone.utc)


class MembershipManager(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.expiry_check.start()

    def cog_unload(self) -> None:
        self.expiry_check.cancel()

    async def _notify(self, channel_id: int, embed: discord.Embed) -> None:
        channel = self.bot.get_channel(channel_id)
        if isinstance(channel, discord.TextChannel):
            try:
                await channel.send(embed=embed)
            except discord.HTTPException:
                log.exception("Membership notification failed")

    async def _audit_actor(self, member: discord.Member) -> str:
        try:
            async for entry in member.guild.audit_logs(
                limit=8, action=discord.AuditLogAction.member_role_update
            ):
                if entry.target and entry.target.id == member.id:
                    if (discord.utils.utcnow() - entry.created_at).total_seconds() <= 20:
                        return f"{entry.user} ({entry.user.id})" if entry.user else "Unknown / unavailable"
        except (discord.Forbidden, discord.HTTPException):
            pass
        return "Unknown / unavailable"

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if after.guild.id != config.SERVER_A_ID or after.bot:
            return
        had_role = any(role.id == config.MENTORSHIP_ROLE_ID for role in before.roles)
        has_role = any(role.id == config.MENTORSHIP_ROLE_ID for role in after.roles)
        if had_role == has_role:
            return

        actor = await self._audit_actor(after)
        now = discord.utils.utcnow()
        if has_role:
            existing = await self.bot.database.get_subscription(after.guild.id, after.id)
            if existing:
                await self.bot.database.set_subscription_active(after.guild.id, after.id, True)
            else:
                await self.bot.database.upsert_subscription(
                    after.guild.id, after.id, started_at=now, source="discord_role"
                )
            # A role restoration means the member renewed. Remove any old renewal ticket.
            open_tickets = await self.bot.database.get_open_tickets_for_user(
                after.guild.id, after.id
            )
            for ticket in open_tickets:
                if ticket["ticket_type"] == "renewal":
                    ticket_channel = after.guild.get_channel(ticket["channel_id"])
                    await self.bot.database.close_ticket(ticket["channel_id"])
                    if ticket_channel:
                        try:
                            await ticket_channel.delete(reason="Mentorship role restored")
                        except discord.HTTPException:
                            log.exception("Could not delete renewed member ticket %s", ticket_channel.id)
            title, status, color = "Mentorship role assigned / renewed", "Inactive → Active", discord.Color.green()
            event_type = "mentorship_role_added"
        else:
            # Keep expiry records scheduled; the expiry worker re-checks the source role at expiry.
            title, status, color = "Mentorship role removed", "Role absent; expiry check remains scheduled", discord.Color.red()
            event_type = "mentorship_role_removed"

        embed = discord.Embed(title=title, color=color, timestamp=now)
        embed.add_field(name="Member", value=f"{after.mention}\n{after} ({after.id})", inline=False)
        embed.add_field(name="Status", value=status, inline=True)
        embed.add_field(name="Changed by", value=actor, inline=True)
        embed.set_footer(text="Server A")
        await self._notify(
            config.ROLE_ASSIGNED_CHANNEL_ID if has_role else config.ROLE_REMOVED_CHANNEL_ID,
            embed,
        )
        if has_role:
            await self._notify(config.SALES_CHANNEL_ID, embed)
            ticket_cog = self.bot.get_cog("TicketManager")
            if ticket_cog:
                try:
                    await ticket_cog.send_server_b_invite(after)
                except Exception:
                    log.exception("Could not send Server B invite to %s", after.id)
        await self.bot.database.add_audit_event(
            after.guild.id, event_type, target_id=after.id,
            details={"actor": actor, "role_id": config.MENTORSHIP_ROLE_ID, "status": status},
        )

    @tasks.loop(minutes=15)
    async def expiry_check(self) -> None:
        try:
            records = await self.bot.database.list_expired_subscriptions()
            guild_a = self.bot.get_guild(config.SERVER_A_ID)
            guild_b = self.bot.get_guild(config.SERVER_B_ID)
            if guild_a is None or guild_b is None:
                return
            for record in records:
                user_id = int(record["user_id"])
                member_a = guild_a.get_member(user_id)
                if member_a is None:
                    try:
                        member_a = await guild_a.fetch_member(user_id)
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                        member_a = None

                still_has_role = bool(member_a and any(
                    role.id == config.MENTORSHIP_ROLE_ID for role in member_a.roles
                ))
                if still_has_role:
                    started = datetime.fromisoformat(record["started_at"].replace("Z", "+00:00"))
                    await self.bot.database.upsert_subscription(
                        guild_a.id, user_id, started_at=started, expires_at=None,
                        source=record["source"], active=True,
                    )
                    continue

                member_b = guild_b.get_member(user_id)
                if member_b:
                    try:
                        await member_b.kick(reason="Membership expired; Mentorship role absent in Server A")
                    except (discord.Forbidden, discord.HTTPException):
                        log.exception("Could not kick expired member %s", user_id)

                await self.bot.database.set_subscription_active(guild_a.id, user_id, False)
                renewal_url = await self.bot.database.get_setting("superprofile_renewal_url")
                delivered = False
                recipient = member_a
                if recipient is None:
                    try:
                        recipient = await self.bot.fetch_user(user_id)
                    except (discord.NotFound, discord.HTTPException):
                        recipient = None
                if recipient and renewal_url:
                    try:
                        await recipient.send(f"Your Mentorship access expired. Renew here: {renewal_url}")
                        delivered = True
                    except discord.Forbidden:
                        pass
                    except discord.HTTPException:
                        log.exception("Renewal DM failed for %s", user_id)

                if not delivered and member_a:
                    ticket_cog = self.bot.get_cog("TicketManager")
                    if ticket_cog:
                        open_tickets = await self.bot.database.get_open_tickets_for_user(guild_a.id, user_id)
                        if not any(t["ticket_type"] == "renewal" for t in open_tickets):
                            opening = (
                                f"Hello {member_a.mention}. Your membership has expired. "
                                + (f"Renew here: {renewal_url}" if renewal_url
                                   else "Please contact staff for the renewal link.")
                            )
                            try:
                                await ticket_cog.create_private_ticket(
                                    guild_a, member_a, "renewal", opening_message=opening
                                )
                            except (discord.Forbidden, discord.HTTPException, RuntimeError):
                                log.exception("Renewal ticket creation failed for %s", user_id)
        except Exception:
            log.exception("Membership expiry cycle failed")

    @expiry_check.before_loop
    async def before_expiry_check(self) -> None:
        await self.bot.wait_until_ready()

    @app_commands.command(name="syncmember", description="Re-check a member's Mentorship role and send their private invite if eligible.")
    @app_commands.checks.has_permissions(administrator=True)
    async def syncmember(self, interaction: discord.Interaction, member: discord.Member) -> None:
        if interaction.guild is None or interaction.guild.id != config.SERVER_A_ID:
            await interaction.response.send_message("Use this command in Server A.", ephemeral=True)
            return
        if not any(role.id == config.MENTORSHIP_ROLE_ID for role in member.roles):
            await interaction.response.send_message(
                "This member does not currently have the Mentorship role. No invitation was sent.",
                ephemeral=True,
            )
            return
        existing = await self.bot.database.get_subscription(interaction.guild.id, member.id)
        if existing:
            await self.bot.database.set_subscription_active(interaction.guild.id, member.id, True)
        else:
            await self.bot.database.upsert_subscription(
                interaction.guild.id, member.id, started_at=utcnow(), source="admin_sync"
            )
        ticket_cog = self.bot.get_cog("TicketManager")
        if not ticket_cog:
            await interaction.response.send_message("Ticket/invitation service is unavailable.", ephemeral=True)
            return
        sent = await ticket_cog.send_server_b_invite(member)
        await interaction.response.send_message(
            "Membership record synchronized. " +
            ("Invitation delivered or fallback ticket created." if sent
             else "The invite could not be delivered; check bot permissions and logs."),
            ephemeral=True,
        )

    @app_commands.command(name="setmembershipexpiry", description="Record a member's UTC membership expiry.")
    @app_commands.checks.has_permissions(administrator=True)
    async def setmembershipexpiry(
        self, interaction: discord.Interaction, member: discord.Member, expiry_iso: str
    ) -> None:
        if interaction.guild is None or interaction.guild.id != config.SERVER_A_ID:
            await interaction.response.send_message("Use this command in Server A.", ephemeral=True)
            return
        if not any(role.id == config.MENTORSHIP_ROLE_ID for role in member.roles):
            await interaction.response.send_message("That member does not have the Mentorship role.", ephemeral=True)
            return
        try:
            expiry = parse_expiry(expiry_iso)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await self.bot.database.upsert_subscription(
            interaction.guild.id, member.id, started_at=utcnow(),
            expires_at=expiry, source="admin_recorded", active=True,
        )
        await interaction.response.send_message(
            f"Expiry saved for {member.mention}: <t:{int(expiry.timestamp())}:F>.",
            ephemeral=True,
        )

    @app_commands.command(name="recordrenewal", description="Record renewal when the Mentorship role did not change.")
    @app_commands.checks.has_permissions(administrator=True)
    async def recordrenewal(
        self, interaction: discord.Interaction, member: discord.Member, expiry_iso: str
    ) -> None:
        if interaction.guild is None or interaction.guild.id != config.SERVER_A_ID:
            await interaction.response.send_message("Use this command in Server A.", ephemeral=True)
            return
        if not any(role.id == config.MENTORSHIP_ROLE_ID for role in member.roles):
            await interaction.response.send_message("The member must have the Mentorship role.", ephemeral=True)
            return
        try:
            expiry = parse_expiry(expiry_iso)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await self.bot.database.upsert_subscription(
            interaction.guild.id, member.id, started_at=utcnow(),
            expires_at=expiry, source="admin_recorded_renewal", active=True,
        )
        tickets = await self.bot.database.get_open_tickets_for_user(interaction.guild.id, member.id)
        for ticket in tickets:
            if ticket["ticket_type"] == "renewal":
                channel = interaction.guild.get_channel(ticket["channel_id"])
                await self.bot.database.close_ticket(ticket["channel_id"])
                if channel:
                    try:
                        await channel.delete(reason="Membership renewal recorded")
                    except discord.HTTPException:
                        log.exception("Could not delete renewal ticket %s", channel.id)
        ticket_cog = self.bot.get_cog("TicketManager")
        if ticket_cog:
            await ticket_cog.send_server_b_invite(member)
        await interaction.response.send_message(
            f"Renewal recorded for {member.mention}; expiry <t:{int(expiry.timestamp())}:F>.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MembershipManager(bot))
