import discord
from discord.ext import commands
from discord import app_commands
import database

class ModerationAudit(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="mention_access_add", description="Allow a role to mention a protected member.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(member="Member whose mentions are restricted", role="Role allowed to mention this member")
    async def mention_access_add(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role):
        if interaction.guild is None or role.is_default() or role.guild.id != interaction.guild.id:
            return await interaction.response.send_message(
                "Choose a normal role from this server.", ephemeral=True
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
        protected_targets = [
            target for target in message.mentions if target.id in restrictions
        ]
        if not protected_targets:
            return
        if message.author.guild_permissions.administrator or message.author.guild_permissions.manage_guild:
            return

        # Refresh roles from Discord on every protected-member mention.
        # Combine fresh and cached IDs so a stale gateway cache cannot reject
        # a role that the member actually holds. Any one allowed role is enough.
        sender_role_ids = {
            int(role.id) for role in getattr(message.author, "roles", [])
        }
        try:
            sender = await message.guild.fetch_member(message.author.id)
            sender_role_ids.update(int(role.id) for role in sender.roles)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            # Fail open if Discord cannot verify the member's current roles.
            return

        for target in protected_targets:
            allowed_role_ids = {int(role_id) for role_id in restrictions[target.id]}
            if not sender_role_ids.isdisjoint(allowed_role_ids):
                continue
                try:
                    await message.delete()
                except (discord.Forbidden, discord.HTTPException):
                    return
                try:
                    await message.channel.send(
                        f"{message.author.mention}, don't tag him.",
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
            roles = ", ".join(f"<@&{rid}> (ID: {rid})" for rid in sorted(role_ids))
            lines.append(f"<@{user_id}> — allowed roles: {roles}")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

async def setup(bot):
    await bot.add_cog(ModerationAudit(bot))
