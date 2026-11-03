from __future__ import annotations

import discord
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
        embed = discord.Embed(
            title="Mentorship Bot Setup",
            description="Use the admin commands below to finish configuring the bot.",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Staff role", value="Configured" if staff else "Not configured", inline=True)
        embed.add_field(name="Checkout link", value="Configured" if checkout else "Not configured", inline=True)
        embed.add_field(name="Renewal link", value="Configured" if renewal else "Not configured", inline=True)
        embed.add_field(
            name="Commands",
            value=(
                "• /setstaffrole — choose the staff role\n"
                "• /setcheckoutlink — save your Superprofile purchase URL\n"
                "• /setrenewallink — save your Superprofile renewal URL\n"
                "• /setupstatus — review saved settings"
            ),
            inline=False,
        )
        embed.set_footer(text="Ticket categories are created and expanded automatically.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="setstaffrole", description="Set the role allowed to view private tickets.")
    @app_commands.checks.has_permissions(administrator=True)
    async def setstaffrole(self, interaction: discord.Interaction, role: discord.Role) -> None:
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

    @app_commands.command(name="setupstatus", description="Show whether the required settings are configured.")
    @app_commands.checks.has_permissions(administrator=True)
    async def setupstatus(self, interaction: discord.Interaction) -> None:
        values = {
            "Staff role": await self.bot.database.get_setting("staff_role_id"),
            "Superprofile checkout": await self.bot.database.get_setting("superprofile_checkout_url"),
            "Superprofile renewal": await self.bot.database.get_setting("superprofile_renewal_url"),
        }
        lines = [f"**{name}:** {'Configured' if value else 'Not configured'}"
                 for name, value in values.items()]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SetupCommands(bot))
