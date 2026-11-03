import asyncio
import discord
from discord.ext import commands
import database

class ModerationAudit(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _send_to(self, guild_id, channel_id, embed):
        guild = self.bot.get_guild(guild_id)
        channel = guild.get_channel(channel_id) if guild and channel_id else None
        if channel:
            try:
                await channel.send(embed=embed)
            except discord.HTTPException:
                pass

    async def _forward(self, source_guild, title, description, color):
        cfg = await database.get_config(source_guild.id)
        if not cfg or not cfg.get("server_c_id") or not cfg.get("log_channel_id"):
            return
        embed = discord.Embed(title=title, description=description, color=color)
        await self._send_to(cfg["server_c_id"], cfg["log_channel_id"], embed)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        cfg = await database.get_config(after.guild.id)
        if not cfg or after.guild.id != cfg["server_a_id"]:
            return
        added = set(after.roles) - set(before.roles)
        removed = set(before.roles) - set(after.roles)
        for role, assigned in [(r, True) for r in added] + [(r, False) for r in removed]:
            embed = discord.Embed(
                title="🟢 Role assigned" if assigned else "🔴 Role revoked",
                color=discord.Color.green() if assigned else discord.Color.red())
            embed.add_field(name="Member", value=f"{after} ({after.id})", inline=False)
            embed.add_field(name="Role", value=f"{role.name} ({role.id})", inline=False)
            try:
                async for entry in after.guild.audit_logs(
                    limit=10, action=discord.AuditLogAction.member_role_update):
                    if entry.target and entry.target.id == after.id:
                        embed.add_field(name="Changed by", value=str(entry.user), inline=False)
                        break
            except discord.HTTPException:
                pass
            await self._send_to(cfg["server_a_id"], cfg["audit_channel_id"], embed)

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        cfg = await database.get_config(guild.id)
        if cfg and guild.id == cfg["server_a_id"]:
            await self._forward(guild, "Member banned",
                f"{user} ({user.id}) was banned from Server A.", discord.Color.red())

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        cfg = await database.get_config(member.guild.id)
        if not cfg or member.guild.id != cfg["server_a_id"]:
            return
        await asyncio.sleep(1)
        try:
            async for entry in member.guild.audit_logs(
                limit=8, action=discord.AuditLogAction.kick):
                if entry.target and entry.target.id == member.id:
                    await self._forward(member.guild, "Member kicked",
                        f"{member} ({member.id}) was kicked by {entry.user}.",
                        discord.Color.orange())
                    return
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if message.guild is None:
            return
        cfg = await database.get_config(message.guild.id)
        if not cfg or message.guild.id != cfg["server_a_id"]:
            return
        content = message.content[:1200] if message.content else "[No cached message content]"
        await self._forward(message.guild, "Message deleted",
            f"Author: {message.author} ({message.author.id})\n"
            f"Channel: {message.channel.mention}\nContent: {content}",
            discord.Color.dark_red())

async def setup(bot):
    await bot.add_cog(ModerationAudit(bot))
