import logging
import discord
from discord.ext import commands, tasks
import database

log = logging.getLogger("reveals-assistant.mentorship")

class Mentorship(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._offboarding: set[tuple[int, int]] = set()
        self.role_verification.start()

    def cog_unload(self):
        self.role_verification.cancel()

    async def _send_role_log(self, guild: discord.Guild, cfg: dict,
                             member_label: str, user_id: int,
                             sub: dict | None, revoked: bool = False):
        from .ticketing import LogActionsView
        email = (sub or {}).get("email") or "Not recorded"
        tenure = (sub or {}).get("tenure", "Not recorded").title()
        embed = discord.Embed(
            title="Mentorship role revoked" if revoked else "Mentorship role assigned",
            color=discord.Color.red() if revoked else discord.Color.green()
        )
        embed.add_field(name="Discord user", value=f"{member_label} ({user_id})", inline=False)
        embed.add_field(name="Email", value=email, inline=True)
        embed.add_field(name="Tenure", value=tenure, inline=True)
        channel_ids = (cfg.get("role_revoked_channel_id"),) if revoked else (
            cfg.get("role_assigned_channel_id"), cfg.get("sales_channel_id")
        )
        for channel_id in channel_ids:
            channel = guild.get_channel(channel_id) if channel_id else None
            if isinstance(channel, discord.TextChannel):
                try:
                    await channel.send(embed=embed, view=LogActionsView(user_id, guild.id))
                except discord.HTTPException:
                    log.exception("Could not send mentorship role log to %s", channel.id)

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
            monthly_url = cfg.get("monthly_url") or cfg.get("renewal_url")
            quarterly_url = cfg.get("quarterly_url")
            if monthly_url and quarterly_url:
                message = (
                    "Your mentorship access has ended. Choose a renewal plan:\\n"
                    f"Monthly: {monthly_url}\\nQuarterly: {quarterly_url}"
                )
            elif monthly_url:
                message = f"Your mentorship access has ended. Renew here: {monthly_url}"
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
                        await create_private_ticket(source, current_member, cfg, "renewal")
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
            await self._send_role_log(
                source, cfg, str(member) if member else f"User {user_id}",
                user_id, sub, revoked=True
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
            # Role assignment alone is deliberately NOT proof of payment and never grants Server B access.
            await self._send_role_log(after.guild, cfg, str(after), after.id, sub)
        else:
            await self._offboard(
                after.guild, after.id, cfg,
                "Mentorship role removed in Server A", member=after
            )

    @tasks.loop(minutes=20)
    async def role_verification(self):
        for source in self.bot.guilds:
            cfg = await database.get_config(source.id)
            if not cfg or cfg.get("server_a_id") != source.id:
                continue
            role = source.get_role(cfg.get("mentorship_role_id"))
            if role is None:
                log.error("Configured mentorship role missing in Server A %s", source.id)
                continue
            expired = set(await database.expired_subscriptions(source.id))
            for sub in await database.active_subscriptions(source.id):
                user_id = sub["user_id"]
                member = source.get_member(user_id)
                if member is None:
                    try:
                        member = await source.fetch_member(user_id)
                    except discord.NotFound:
                        member = None
                    except discord.HTTPException:
                        log.exception("Could not fetch Server A member %s", user_id)
                        continue
                if user_id in expired and member and role in member.roles:
                    try:
                        await member.remove_roles(role, reason="Mentorship subscription expired")
                    except discord.HTTPException:
                        log.exception("Could not remove expired role for %s", user_id)
                        continue
                    # The event listener will offboard and notify. The next loop is a retry safety net.
                    await self._offboard(source, user_id, cfg,
                                         "Mentorship subscription expired", member=member)
                elif member is None or role not in member.roles or user_id in expired:
                    await self._offboard(source, user_id, cfg,
                                         "20-minute mentorship verification/expiry check",
                                         member=member)
                    log.info("Offboarded %s after role verification", user_id)

    @role_verification.before_loop
    async def before_role_verification(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Mentorship(bot))
