import asyncio
import discord
from discord.ext import commands\nfrom discord import app_commands
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

    @app_commands.command(name="mention_access_add", description="Allow a role to mention a protected member.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(member="Member whose mentions are restricted", role="Role allowed to mention this member")
    async def mention_access_add(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role):
        if interaction.guild is None or role.is_default or role >= interaction.guild.me.top_role:
            return await interaction.response.send_message(
                "Choose a normal role below the bot's highest role, inside this server.", ephemeral=True
            )
        await database.add_mention_allowed_role(interaction.guild.id, member.id, role.id)
        await interaction.response.send_message(
            f"{role.mention} can now mention {member.mention}. Other members cannot mention them.",
            allowed_mentions=discord.AllowedMentions(roles=True, users=True), ephemeral=True
        )

    @app_commands.command(name="mention_access_remove", description="Remove a role's permission to mention a protected member.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def mention_access_remove(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role):
        if interaction.guild is None:
            return await interaction.response.send_message("Use this command in a server.", ephemeral=True)
        removed = await database.remove_mention_allowed_role(interaction.guild.id, member.id, role.id)
        await interaction.response.send_message(
            f"Removed {role.mention} from {member.mention}'s allowed mention roles."
            if removed else "That role was not on the allowed list.",
            ephemeral=True
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None or message.author.bot or not message.mentions:
            return
        restrictions = await database.get_protected_member_mention_roles(message.guild.id)
        if not restrictions:
            return
        protected_ids = {member_id for member_id in message.mentions if member_id.id in restrictions}
        if not protected_ids:
            return
        if message.author.guild_permissions.administrator or message.author.guild_permissions.manage_guild:
            return
        author_role_ids = {role.id for role in getattr(message.author, "roles", [])}
        for target in protected_ids:
            if author_role_ids.isdisjoint(restrictions[target.id]):
                try:
                    await message.delete()
                except discord.Forbidden:
                    return
                except discord.HTTPException:
                    return
                try:
                    await message.channel.send(
                        f"{message.author.mention}, you don't have permission to mention {target.mention}.",
                        allowed_mentions=discord.AllowedMentions(users=True)
                    )
                except discord.HTTPException:
                    pass
                return

    @app_commands.command(name="mention_access_list", description="Show protected members and their allowed mention roles.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def mention_access_list(self, interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message("Use this command in a server.", ephemeral=True)
        restrictions = await database.get_protected_member_mention_roles(interaction.guild.id)
        if not restrictions:
            return await interaction.response.send_message("No member mention restrictions are configured.", ephemeral=True)
        lines = []
        for user_id, role_ids in restrictions.items():
            roles = ", ".join(f"<@&{rid}>" for rid in sorted(role_ids))
            lines.append(f"<@{user_id}> — allowed roles: {roles}")
        await interaction.response.send_message("\\n".join(lines), ephemeral=True)

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
