from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

import config


class AdminTools(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="broadcast", description="Send a message to every text channel in a category.")
    @app_commands.checks.has_permissions(administrator=True)
    async def broadcast(
        self, interaction: discord.Interaction, category: discord.CategoryChannel, message: str
    ) -> None:
        if interaction.guild is None or interaction.guild.id != config.SERVER_A_ID:
            await interaction.response.send_message("Use this command in Server A.", ephemeral=True)
            return
        if not message.strip() or len(message) > 2000:
            await interaction.response.send_message(
                "The broadcast must contain 1–2000 characters.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        sent = failed = skipped = 0
        for channel in category.text_channels:
            perms = channel.permissions_for(interaction.guild.me)
            if not perms.view_channel or not perms.send_messages:
                skipped += 1
                continue
            try:
                await channel.send(message, allowed_mentions=discord.AllowedMentions.none())
                sent += 1
            except discord.Forbidden:
                failed += 1
            except discord.HTTPException:
                failed += 1
        await interaction.followup.send(
            f"Broadcast finished. Sent: **{sent}** · Failed: **{failed}** · "
            f"Skipped: **{skipped}**.", ephemeral=True
        )

    @app_commands.command(name="closemyticket", description="Delete your own ticket.")
    async def closemyticket(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("Use this inside your ticket.", ephemeral=True)
            return
        cursor = await self.bot.database._db().execute(
            "SELECT user_id FROM tickets WHERE channel_id=? AND status='open'",
            (interaction.channel.id,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        if not row or int(row["user_id"]) != interaction.user.id:
            await interaction.response.send_message(
                "Only the ticket creator can use this command.", ephemeral=True
            )
            return
        channel = interaction.channel
        await self.bot.database.close_ticket(channel.id)
        await interaction.response.send_message("Your ticket is being deleted.", ephemeral=True)
        await channel.delete(reason="Ticket creator closed their ticket")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminTools(bot))
