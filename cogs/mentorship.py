import logging
import asyncio
from datetime import datetime, timezone
import discord
from discord.ext import commands
import database

log = logging.getLogger("reveals-assistant.mentorship")

class Mentorship(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._offboarding: set[tuple[int, int]] = set()

    async def _find_role_assigner(self, guild: discord.Guild, member_id: int, role_id: int):
        # Discord audit-log entries can arrive just after the member update event.
        await asyncio.sleep(1)
        try:
            async for entry in guild.audit_logs(limit=12, action=discord.AuditLogAction.member_role_update):
                target = getattr(entry.target, "id", None)
                if target != member_id or not entry.user:
                    continue
                if (datetime.now(timezone.utc) - entry.created_at).total_seconds() > 90:
                    continue
                before_roles = {r.id for r in (getattr(entry.before, "roles", None) or [])}
                after_roles = {r.id for r in (getattr(entry.after, "roles", None) or [])}
                if role_id in after_roles and role_id not in before_roles:
                    return entry.user
        except discord.Forbidden:
            log.warning("Missing View Audit Log permission in guild %s", guild.id)
        except discord.HTTPException:
            log.exception("Could not inspect role assignment audit log in guild %s", guild.id)
        return None

    async def _send_role_log(self, guild: discord.Guild, cfg: dict,
                             member_label: str, user_id: int,
                             sub: dict | None, role: discord.Role,
                             assigned_by: discord.abc.User | None = None,
                             revoked: bool = False):
        from .ticketing import LogActionsView
        email = (sub or {}).get("email") or "Not recorded"
        embed = discord.Embed(
            title="Mentorship role revoked" if revoked else "Mentorship role assigned",
            color=discord.Color.red() if revoked else discord.Color.green()
        )
        embed.add_field(name="Discord user", value=f"{member_label} ({user_id})", inline=False)
        embed.add_field(name="Role", value=role.mention, inline=True)
        if not revoked:
            embed.add_field(name="Assigned by",
                            value=assigned_by.mention if assigned_by else "Unknown (Discord audit log unavailable)",
                            inline=True)
        embed.add_field(name="Email", value=email, inline=True)
        embed.add_field(name="Access duration", value="Role-based access — no expiry tracking", inline=False)
        channel_id = cfg.get("role_revoked_channel_id") if revoked else cfg.get("role_assigned_channel_id")
        channel = guild.get_channel(channel_id) if channel_id else None
        if isinstance(channel, discord.TextChannel):
            try:
                await channel.send(embed=embed, view=LogActionsView(user_id, guild.id) if revoked else None)
            except discord.HTTPException:
                log.exception("Could not send mentorship role log to %s", channel.id)

    async def _grant_community_access(self, member: discord.Member, cfg: dict,
                                      sub: dict | None = None):
        from .ticketing import create_private_ticket
        community = self.bot.get_guild(cfg.get("server_b_id"))
        if community is None:
            log.error("Server B %s is unavailable; cannot grant access to %s", cfg.get("server_b_id"), member.id)
            return
        invite_channel = next((ch for ch in community.text_channels
                               if community.me and ch.permissions_for(community.me).create_instant_invite), None)
        if invite_channel is None:
            log.error("No Server B channel allows Create Instant Invite for member %s", member.id)
            return
        try:
            invite = await invite_channel.create_invite(
                max_uses=1, max_age=86400, unique=True,
                reason=f"Payment-verified role assigned to {member.id}"
            )
        except discord.HTTPException:
            log.exception("Could not create Server B invite for %s", member.id)
            return
        ticket_id = await database.find_open_ticket(member.guild.id, member.id, "purchase")
        if ticket_id is None:
            ticket_id = await database.find_open_ticket(member.guild.id, member.id, "renewal")
        ticket_channel = member.guild.get_channel(ticket_id) if ticket_id else None
        if not isinstance(ticket_channel, discord.TextChannel):
            try:
                ticket_channel = await create_private_ticket(member.guild, member, cfg, "purchase",
                                                              (sub or {}).get("email"))
            except (discord.HTTPException, ValueError):
                log.exception("Could not create access-delivery ticket for %s", member.id)
                ticket_channel = None
        message = (f"Payment verified automatically because you received the configured membership role. "
                   f"Join Server B using your one-use invite (expires in 24 hours): {invite.url}")
        try:
            await member.send(message)
        except discord.HTTPException:
            log.warning("Could not DM Server B invite to %s", member.id)
        if isinstance(ticket_channel, discord.TextChannel):
            try:
                await ticket_channel.send(f"{member.mention} {message}")
            except discord.HTTPException:
                log.exception("Could not post Server B invite in ticket for %s", member.id)

    async def _kick_from_community(self, cfg: dict, user_id: int, reason: str):
        community = self.bot.get_guild(cfg.get("server_b_id"))
        if community is None:
            log.error("Server B %s is unavailable; cannot offboard %s",
                      cfg.get("server_b_id"), user_id)
            return
        try:
            member = community.get_member(user_id) or await community.fetch_member(user_id)
        except discord.NotFound:
            return
        except discord.HTTPException:
            log.exception("Could not fetch Server B member %s", user_id)
            return
        if member:
            try:
                await member.kick(reason=reason)
            except discord.HTTPException:
                log.exception("Could not kick %s from Server B", user_id)

    async def _offboard(self, source: discord.Guild, user_id: int,
                        cfg: dict, reason: str, member: discord.Member | None = None):
        key = (source.id, user_id)
        if key in self._offboarding:
            return
        self._offboarding.add(key)
        try:
            sub = await database.get_subscription(user_id, source.id)
            await self._kick_from_community(cfg, user_id, reason)
            renewal_url = cfg.get("renewal_url") or cfg.get("monthly_url")
            if renewal_url:
                message = f"Your mentorship access has ended. Renew your access here: {renewal_url}"
            else:
                message = "Your mentorship access has ended. Please contact the team to renew."
            dm_sent = False
            try:
                user = await self.bot.fetch_user(user_id)
                await user.send(message)
                dm_sent = True
            except discord.HTTPException:
                log.info("Renewal DM could not be delivered to %s", user_id)
            if not dm_sent:
                current_member = member or source.get_member(user_id)
                if current_member:
                    try:
                        from .ticketing import create_private_ticket
                        await create_private_ticket(
                            source, current_member, cfg, "renewal",
                            (sub or {}).get("email")
                        )
                    except (discord.HTTPException, ValueError):
                        log.exception("Could not create renewal ticket for %s", user_id)
                else:
                    sales = source.get_channel(cfg.get("sales_channel_id"))
                    if isinstance(sales, discord.TextChannel):
                        await sales.send(
                            f"Renewal DM failed and user {user_id} is no longer in Server A. "
                            "Contact them through the verified support channel."
                        )
            await database.deactivate_subscription(user_id, source.id)
            role = source.get_role(cfg.get("mentorship_role_id"))
            if role:
                await self._send_role_log(
                    source, cfg, str(member) if member else f"User {user_id}",
                    user_id, sub, role, revoked=True
                )
        finally:
            self._offboarding.discard(key)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        cfg = await database.get_config(after.guild.id)
        if not cfg or after.guild.id != cfg.get("server_a_id"):
            return
        role = after.guild.get_role(cfg.get("mentorship_role_id"))
        if role is None or ((role in before.roles) == (role in after.roles)):
            return
        sub = await database.get_subscription(after.id, after.guild.id)
        if role in after.roles:
            # The configured provider role is the payment-verification signal.
            actor = await self._find_role_assigner(after.guild, after.id, role.id)
            await self._grant_community_access(after, cfg, sub)
            await self._send_role_log(after.guild, cfg, str(after), after.id, sub, role, assigned_by=actor)
        else:
            await self._offboard(
                after.guild, after.id, cfg,
                "Mentorship role removed in Server A", member=after
            )


async def setup(bot):
    await bot.add_cog(Mentorship(bot))
