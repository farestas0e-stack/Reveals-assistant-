from __future__ import annotations

import discord
import config
from discord import app_commands
from discord.ext import commands


class SetupCommands(commands.Cog):
    """Admin-only Discord commands for settings that should not require code edits."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="setup", description="Show the bot setup checklist.")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup(self, interaction: discord.Interaction) -> None:
        staff = await self.bot.database.get_setting("staff_role_id")
        checkout = await self.bot.database.get_setting("superprofile_checkout_url")
        renewal = await self.bot.database.get_setting("superprofile_renewal_url")
        moderation = await self.bot.database.get_setting("moderation_log_channel_id")
        embed = discord.Embed(
            title="Mentorship Bot Setup",
            description="Use the admin commands below to finish configuring the bot.",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Staff role", value="Configured" if staff else "Not configured", inline=True)
        embed.add_field(name="Checkout link", value="Configured" if checkout else "Not configured", inline=True)
        embed.add_field(name="Renewal link", value="Configured" if renewal else "Not configured", inline=True)
        embed.add_field(name="Moderation log channel", value="Configured" if moderation else "Not configured", inline=True)
        embed.add_field(
            name="Commands",
            value=(
                "• /setstaffrole — choose the staff role\n"
                "• /setlink — save your checkout or renewal URL\n"
                "• /setmembershipexpiry — record a member expiry\n"
                "• /recordrenewal — record renewal when the role stays assigned\\n"
                "• /setmoderationchannel — choose the Server C log channel\n                "• /setinvitechannel — choose the Server B invite channel"
            ),
            inline=False,
        )
        embed.set_footer(text="Ticket categories are created and expanded automatically.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="setstaffrole", description="Set the role allowed to view private tickets.")
    @app_commands.checks.has_permissions(administrator=True)
    async def setstaffrole(self, interaction: discord.Interaction, role: discord.Role) -> None:
        if interaction.guild is None or interaction.guild.id != config.SERVER_A_ID:
            await interaction.response.send_message("Run this command in Server A.", ephemeral=True)
            return
        await self.bot.database.set_setting("staff_role_id", str(role.id))
        await interaction.response.send_message(
            f"Private tickets will be visible to {role.mention}, the ticket creator and the bot.",
            ephemeral=True,
        )

    async def _save_url(self, interaction: discord.Interaction, key: str, label: str, url: str) -> None:
        cleaned = url.strip()
        if not cleaned.startswith("https://") or len(cleaned) > 500:
            await interaction.response.send_message(
                "Please provide a valid HTTPS link (starting with https://).", ephemeral=True
            )
            return
        await self.bot.database.set_setting(key, cleaned)
        await interaction.response.send_message(f"{label} link saved.", ephemeral=True)

    @app_commands.command(name="setcheckoutlink", description="Save your Superprofile purchase link.")
    @app_commands.checks.has_permissions(administrator=True)
    async def setcheckoutlink(self, interaction: discord.Interaction, url: str) -> None:
        await self._save_url(interaction, "superprofile_checkout_url", "Checkout", url)

    @app_commands.command(name="setrenewallink", description="Save your Superprofile renewal link.")
    @app_commands.checks.has_permissions(administrator=True)
    async def setrenewallink(self, interaction: discord.Interaction, url: str) -> None:
        await self._save_url(interaction, "superprofile_renewal_url", "Renewal", url)

    @app_commands.command(name="setlink", description="Set the checkout or renewal payment URL.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.choices(link_type=[
        app_commands.Choice(name="Purchase / checkout", value="checkout"),
        app_commands.Choice(name="Renewal", value="renewal"),
    ])
    async def setlink(
        self, interaction: discord.Interaction,
        link_type: app_commands.Choice[str], url: str
    ) -> None:
        key = "superprofile_checkout_url" if link_type.value == "checkout" else "superprofile_renewal_url"
        label = "Checkout" if link_type.value == "checkout" else "Renewal"
        await self._save_url(interaction, key, label, url)

    @app_commands.command(name="setupstatus", description="Show whether the required settings are configured.")
    @app_commands.checks.has_permissions(administrator=True)
    async def setupstatus(self, interaction: discord.Interaction) -> None:
        values = {
            "Staff role": await self.bot.database.get_setting("staff_role_id"),
            "Superprofile checkout": await self.bot.database.get_setting("superprofile_checkout_url"),
            "Superprofile renewal": await self.bot.database.get_setting("superprofile_renewal_url"),
            "Server C moderation channel": await self.bot.database.get_setting("moderation_log_channel_id"),
        }
        lines = [f"**{name}:** {'Configured' if value else 'Not configured'}"
                 for name, value in values.items()]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @app_commands.command(name="setinvitechannel", description="Choose the Server B channel used to create member invitations.")
    @app_commands.checks.has_permissions(administrator=True)
    async def setinvitechannel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ) -> None:
        if interaction.guild is None or interaction.guild.id != config.SERVER_B_ID:
            await interaction.response.send_message(
                "Run this command in Server B and select a channel where the bot can create invites.",
                ephemeral=True,
            )
            return
        permissions = channel.permissions_for(interaction.guild.me)
        if not permissions.view_channel or not permissions.create_instant_invite:
            await interaction.response.send_message(
                "I need View Channel and Create Invite permissions in that channel.",
                ephemeral=True,
            )
            return
        await self.bot.database.set_setting("server_b_invite_channel_id", str(channel.id))
        await interaction.response.send_message(
            f"New member invitations will be created in {channel.mention}.",
            ephemeral=True,
        )

    @app_commands.command(name="setmoderationchannel", description="Choose the moderation log channel in Server C.")
    @app_commands.checks.has_permissions(administrator=True)
    async def setmoderationchannel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ) -> None:
        if interaction.guild is None or interaction.guild.id != config.SERVER_C_ID:
            await interaction.response.send_message(
                "Run this command in Server C, then select its moderation log channel.",
                ephemeral=True,
            )
            return
        await self.bot.database.set_setting("moderation_log_channel_id", str(channel.id))
        await interaction.response.send_message(
            f"Moderation events will be forwarded to {channel.mention}.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SetupCommands(bot))
