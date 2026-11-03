from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

import config

log = logging.getLogger(__name__)


class ModerationLogs(commands.Cog):
    """Forwards moderation events from Server A to a chosen channel in Server C."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _send(self, embed: discord.Embed) -> None:
        server_c = self.bot.get_guild(config.SERVER_C_ID)
        if server_c is None:
            return
        channel_value = await self.bot.database.get_setting("moderation_log_channel_id")
        if not channel_value:
            log.warning("Run /setmoderationchannel in Server C before moderation events can be logged.")
            return
        try:
            channel_id = int(channel_value)
        except ValueError:
            channel_id = 0
        channel = server_c.get_channel(channel_id) if channel_id else None
        if channel is None and channel_id:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                channel = None
        if not isinstance(channel, discord.TextChannel):
            log.warning("Configured moderation log channel is missing or is not a text channel.")
            return
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            log.exception("Could not send moderation log")

    async def _find_actor(
        self, guild: discord.Guild, action: discord.AuditLogAction, target_id: int,
        *, channel_id: int | None = None,
    ) -> str | None:
        try:
            async for entry in guild.audit_logs(limit=12, action=action):
                if not entry.target or entry.target.id != target_id:
                    continue
                if (discord.utils.utcnow() - entry.created_at).total_seconds() > 30:
                    continue
                if channel_id is not None:
                    extra_channel = getattr(entry.extra, "channel", None)
                    if extra_channel and extra_channel.id != channel_id:
                        continue
                return f"{entry.user} ({entry.user.id})" if entry.user else "Unknown / unavailable"
        except (discord.Forbidden, discord.HTTPException):
            log.debug("Audit log lookup unavailable", exc_info=True)
        return None

    async def _find_bulk_delete_actor(self, guild: discord.Guild, channel_id: int) -> str | None:
        try:
            async for entry in guild.audit_logs(
                limit=10, action=discord.AuditLogAction.message_bulk_delete
            ):
                if entry.target and entry.target.id == channel_id:
                    if (discord.utils.utcnow() - entry.created_at).total_seconds() <= 30:
                        return f"{entry.user} ({entry.user.id})" if entry.user else "Unknown / unavailable"
        except (discord.Forbidden, discord.HTTPException):
            log.debug("Bulk-delete audit lookup unavailable", exc_info=True)
        return None

    def _embed(self, title: str, description: str, color: discord.Color) -> discord.Embed:
        return discord.Embed(title=title, description=description, color=color,
                             timestamp=discord.utils.utcnow())

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User) -> None:
        if guild.id != config.SERVER_A_ID:
            return
        await asyncio.sleep(1)
        actor = await self._find_actor(guild, discord.AuditLogAction.ban, user.id)
        await self._send(self._embed(
            "Member banned",
            f"**User:** {user} ({user.id})\n**Moderator:** {actor or 'Unknown / unavailable'}",
            discord.Color.red(),
        ))

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User) -> None:
        if guild.id != config.SERVER_A_ID:
            return
        await asyncio.sleep(1)
        actor = await self._find_actor(guild, discord.AuditLogAction.unban, user.id)
        await self._send(self._embed(
            "Member unbanned",
            f"**User:** {user} ({user.id})\n**Moderator:** {actor or 'Unknown / unavailable'}",
            discord.Color.green(),
        ))

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        if not message.guild or message.guild.id != config.SERVER_A_ID or message.author.bot:
            return
        await asyncio.sleep(1)
        actor = await self._find_actor(
            message.guild, discord.AuditLogAction.message_delete,
            message.author.id, channel_id=message.channel.id,
        )
        body = message.content[:900] if message.content else "[No text content]"
        if message.attachments:
            body += "\nAttachments: " + ", ".join(a.url for a in message.attachments[:3])
        await self._send(self._embed(
            "Message deleted",
            f"**Author:** {message.author} ({message.author.id})\n"
            f"**Channel:** {message.channel.mention}\n"
            f"**Deleted by:** {actor or 'Unknown / possibly self-deleted'}\n"
            f"**Content:** {body}",
            discord.Color.orange(),
        ))

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages: list[discord.Message]) -> None:
        if not messages:
            return
        first = messages[0]
        if not first.guild or first.guild.id != config.SERVER_A_ID:
            return
        lines = []
        for message in messages[:8]:
            body = message.content[:120] if message.content else "[No text content]"
            lines.append(f"• {message.author} ({message.author.id}): {body}")
        if len(messages) > 8:
            lines.append(f"…and {len(messages) - 8} more messages.")
        actor = await self._find_bulk_delete_actor(first.guild, first.channel.id)
        embed = self._embed(
            "Bulk messages deleted",
            f"**Channel:** {first.channel.mention}\n**Count:** {len(messages)}\n"
            f"**Deleted by:** {actor or 'Unknown / unavailable'}\n"
            + "\n".join(lines),
            discord.Color.orange(),
        )
        await self._send(embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        if member.guild.id != config.SERVER_A_ID:
            return
        await asyncio.sleep(1)
        actor = await self._find_actor(member.guild, discord.AuditLogAction.kick, member.id)
        if actor is None:
            # Discord sends the same gateway event for a voluntary leave and a kick.
            return
        await self._send(self._embed(
            "Member kicked",
            f"**User:** {member} ({member.id})\n**Moderator:** {actor}",
            discord.Color.dark_orange(),
        ))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ModerationLogs(bot))
