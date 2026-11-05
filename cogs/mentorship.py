import logging
import discord
from discord.ext import commands, tasks
import database

log = logging.getLogger("reveals-assistant.mentorship")

class Mentorship(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.role_verification.start()

    def cog_unload(self):
        self.role_verification.cancel()

    async def _kick_from_community(self, source: discord.Guild, user_id: int, reason: str):
        cfg = await database.get_config(source.id)
        if not cfg:
            return
        community = self.bot.get_guild(cfg["server_b_id"])
        if community is None:
            return
        try:
            member = community.get_member(user_id) or await community.fetch_member(user_id)
        except discord.NotFound:
            member = None
        except discord.HTTPException:
            log.exception("Could not fetch Server B member %s", user_id)
            return
        if member:
            try:
                await member.kick(reason=reason)
            except discord.HTTPException:
                log.exception("Could not kick %s from Server B", user_id)

    async def _offboard(self, source: discord.Guild, user_id: int, cfg: dict, reason: str):
        await self._kick_from_community(source, user_id, reason)
        try:
            user = await self.bot.fetch_user(user_id)
            await user.send(f"Your mentorship access has ended. Renew here: {cfg.get('renewal_url') or cfg.get('monthly_url') or 'Please contact staff.'}")
        except discord.HTTPException:
            try:
                from .ticketing import create_private_ticket
                user = await self.bot.fetch_user(user_id)
                await create_private_ticket(source, user, cfg, "renewal")
            except (discord.HTTPException, discord.Forbidden, RuntimeError):
                log.exception("Could not send offboarding instructions to %s", user_id)
        await database.deactivate_subscription(user_id, source.id)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        cfg = await database.get_config(after.guild.id)
        if not cfg or after.guild.id != cfg.get("server_a_id"):
            return
        role = after.guild.get_role(cfg.get("mentorship_role_id"))
        if role is None or ((role in before.roles) == (role in after.roles)):
            return
        if role in after.roles:
            # A role grant is logged, but never independently grants Server B access.
            embed = discord.Embed(title="Mentorship role assigned", color=discord.Color.green())
            embed.add_field(name="Discord user", value=f"{after} ({after.id})", inline=False)
            embed.add_field(name="Email / tenure", value="Awaiting approved ticket evidence", inline=False)
            for key in ("role_assigned_channel_id", "sales_channel_id"):
                channel = after.guild.get_channel(cfg.get(key))
                if isinstance(channel, discord.TextChannel):
                    await channel.send(embed=embed)
        else:
            await self._offboard(after.guild, after.id, cfg, "Mentorship role removed in Server A")
            channel = after.guild.get_channel(cfg.get("role_revoked_channel_id"))
            if isinstance(channel, discord.TextChannel):
                embed = discord.Embed(title="Mentorship role revoked", description=f"{after} ({after.id})", color=discord.Color.red())
                await channel.send(embed=embed)

    @tasks.loop(minutes=20)
    async def role_verification(self):
        for source in self.bot.guilds:
            cfg = await database.get_config(source.id)
            if not cfg or cfg.get("server_a_id") != source.id:
                continue
            role = source.get_role(cfg.get("mentorship_role_id"))
            if role is None:
                continue
            for sub in await database.active_subscriptions(source.id):
                member = source.get_member(sub["user_id"])
                if member is None:
                    try:
                        member = await source.fetch_member(sub["user_id"])
                    except discord.NotFound:
                        member = None
                    except discord.HTTPException:
                        continue
                if member is None or role not in member.roles:
                    await self._offboard(source, sub["user_id"], cfg, "20-minute mentorship role verification failed")
                    log.info("Offboarded %s after role verification", sub["user_id"])

    @role_verification.before_loop
    async def before_role_verification(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Mentorship(bot))
