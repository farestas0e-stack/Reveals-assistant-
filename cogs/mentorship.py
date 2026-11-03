import logging
import discord
from discord.ext import commands, tasks
import database

log = logging.getLogger("reveals-assistant.mentorship")

class Mentorship(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.expiry_check.start()

    def cog_unload(self):
        self.expiry_check.cancel()

    async def _make_invite(self, guild: discord.Guild) -> discord.Invite:
        me = guild.me
        if me is None:
            raise RuntimeError("Bot member is unavailable in Server B.")
        for channel in guild.text_channels:
            if channel.permissions_for(me).create_instant_invite:
                return await channel.create_invite(max_uses=1, max_age=86400, unique=True,
                                                   reason="Mentorship access")
        raise RuntimeError("No Server B text channel allows invite creation.")

    async def _deliver_invite(self, source: discord.Guild, user: discord.abc.User,
                              community: discord.Guild, cfg: dict):
        invite = await self._make_invite(community)
        try:
            await user.send(f"Your one-use Server B invite expires in 24 hours: {invite.url}")
        except discord.HTTPException:
            from .ticketing import create_private_ticket
            ticket = await create_private_ticket(source, user, cfg, "purchase")
            await ticket.send(f"{user.mention} Your one-use Server B invite expires in 24 hours: {invite.url}")

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        cfg = await database.get_config(after.guild.id)
        if not cfg or after.guild.id != cfg["server_a_id"]:
            return
        role = after.guild.get_role(cfg["mentorship_role_id"])
        if role is None:
            return
        had, has = role in before.roles, role in after.roles
        if had == has:
            return
        community = self.bot.get_guild(cfg["server_b_id"])
        if has:
            await database.save_subscription(after.id, after.guild.id, cfg["subscription_days"])
            sales = after.guild.get_channel(cfg["sales_channel_id"])
            if isinstance(sales, discord.TextChannel):
                embed = discord.Embed(
                    title="Mentorship role assigned",
                    description="Role assignment alert only; payment is not independently confirmed.",
                    color=discord.Color.green())
                embed.add_field(name="Student", value=f"{after.mention} ({after.id})", inline=False)
                embed.add_field(name="Term", value=f"{cfg['subscription_days']} days", inline=True)
                try:
                    await sales.send(embed=embed)
                except discord.HTTPException:
                    log.exception("Could not send sales alert.")
            if community and community.get_member(after.id) is None:
                try:
                    await self._deliver_invite(after.guild, after, community, cfg)
                except (discord.HTTPException, discord.Forbidden, RuntimeError):
                    log.exception("Could not issue invite or renewal ticket for %s", after.id)
        else:
            if community:
                try:
                    member_b = community.get_member(after.id) or await community.fetch_member(after.id)
                except discord.NotFound:
                    member_b = None
                except discord.HTTPException:
                    log.exception("Could not look up %s in Server B.", after.id)
                    member_b = None
                if member_b:
                    try:
                        await member_b.kick(reason="Mentorship role removed in Server A")
                    except discord.HTTPException:
                        log.exception("Could not remove %s from Server B.", after.id)
            await database.deactivate_subscription(after.id, after.guild.id)

    @tasks.loop(minutes=5)
    async def expiry_check(self):
        for source in self.bot.guilds:
            cfg = await database.get_config(source.id)
            if not cfg or cfg["server_a_id"] != source.id:
                continue
            community = self.bot.get_guild(cfg["server_b_id"])
            role = source.get_role(cfg["mentorship_role_id"])
            for user_id in await database.expired_subscriptions(source.id):
                member_b = None
                if community:
                    try:
                        member_b = community.get_member(user_id) or await community.fetch_member(user_id)
                    except discord.NotFound:
                        member_b = None
                    except discord.HTTPException:
                        log.exception("Could not look up expired member %s in Server B; retrying next cycle.", user_id)
                        continue
                if member_b:
                    try:
                        await member_b.kick(reason="Mentorship subscription expired")
                    except discord.Forbidden:
                        log.error("Missing Kick Members permission or role hierarchy for user %s.", user_id)
                        continue
                    except discord.HTTPException:
                        log.exception("Kick failed for expired user %s; retrying next cycle.", user_id)
                        continue

                member_a = source.get_member(user_id)
                if member_a and role and role in member_a.roles:
                    try:
                        await member_a.remove_roles(role, reason="Mentorship subscription expired")
                    except discord.HTTPException:
                        log.exception("Could not remove expired role from %s.", user_id)

                try:
                    user = await self.bot.fetch_user(user_id)
                    await user.send(f"Your mentorship subscription expired. Renew here: {cfg['renewal_url']}")
                except discord.HTTPException:
                    try:
                        from .ticketing import create_private_ticket
                        user = await self.bot.fetch_user(user_id)
                        await create_private_ticket(source, user, cfg, "renewal")
                    except (discord.HTTPException, discord.Forbidden, RuntimeError):
                        log.exception("Could not DM or create renewal ticket for %s.", user_id)
                await database.deactivate_subscription(user_id, source.id)

    @expiry_check.before_loop
    async def before_expiry_check(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Mentorship(bot))
