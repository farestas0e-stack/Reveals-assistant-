from datetime import datetime, timezone
import discord
from discord.ext import commands, tasks
import database

class Mentorship(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.expiry_check.start()

    def cog_unload(self):
        self.expiry_check.cancel()

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
        if has:
            await database.save_subscription(after.id, after.guild.id, cfg["subscription_days"])
            sales = after.guild.get_channel(cfg["sales_channel_id"])
            if sales:
                embed = discord.Embed(title="Mentorship sale detected",
                    color=discord.Color.green(), timestamp=datetime.now(timezone.utc))
                embed.add_field(name="Student", value=f"{after.mention} ({after.id})", inline=False)
                embed.add_field(name="Event", value="Mentorship role assigned", inline=False)
                await sales.send(embed=embed)
            community = self.bot.get_guild(cfg["server_b_id"])
            if community and community.get_member(after.id) is None:
                invite_channel = next((c for c in community.text_channels
                    if c.permissions_for(community.me).create_instant_invite), None)
                if invite_channel:
                    try:
                        invite = await invite_channel.create_invite(max_uses=1, max_age=86400, unique=True)
                        await after.send(f"Your private community invite: {invite.url}")
                    except discord.HTTPException:
                        pass
        else:
            # Role removal is treated as immediate loss of access.
            community = self.bot.get_guild(cfg["server_b_id"])
            member_b = community.get_member(after.id) if community else None
            if member_b:
                try:
                    await member_b.kick(reason="Mentorship role removed in Server A")
                except discord.HTTPException:
                    pass

    @tasks.loop(minutes=15)
    async def expiry_check(self):
        await self.bot.wait_until_ready()
        for source in self.bot.guilds:
            cfg = await database.get_config(source.id)
            if not cfg or cfg["server_a_id"] != source.id:
                continue
            community = self.bot.get_guild(cfg["server_b_id"])
            role = source.get_role(cfg["mentorship_role_id"])
            if not community or not role:
                continue
            for user_id in await database.expired_subscriptions(source.id):
                member_a = source.get_member(user_id)
                if member_a and role in member_a.roles:
                    await database.save_subscription(user_id, source.id, cfg["subscription_days"])
                    continue
                member_b = community.get_member(user_id)
                if member_b is None:
                    await database.deactivate_subscription(user_id, source.id)
                    continue
                # Attempt the kick first, then notify; if DM fails, create a renewal ticket.
                try:
                    await member_b.kick(reason="Mentorship subscription expired")
                except discord.HTTPException:
                    continue
                try:
                    await self.bot.fetch_user(user_id)
                    user = await self.bot.fetch_user(user_id)
                    await user.send(f"Your mentorship access expired. Renew here: {cfg['renewal_url']}")
                except discord.HTTPException:
                    from .ticketing import create_private_ticket
                    try:
                        await create_private_ticket(source, await self.bot.fetch_user(user_id), cfg, "renewal")
                    except discord.HTTPException:
                        pass
                await database.deactivate_subscription(user_id, source.id)

async def setup(bot):
    await bot.add_cog(Mentorship(bot))
