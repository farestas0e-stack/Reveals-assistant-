import discord
from discord import app_commands
from discord.ext import commands
import database


class ConfirmCategoryRemoval(discord.ui.View):
    def __init__(self, bot, category_id: int, requester_id: int):
        super().__init__(timeout=60)
        self.bot = bot
        self.category_id = category_id
        self.requester_id = requester_id

    @discord.ui.button(label="Confirm permanent deletion", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.requester_id:
            return await interaction.response.send_message(
                "Only the administrator who started this action can confirm it.",
                ephemeral=True,
            )
        guild = interaction.guild
        if guild is None:
            return await interaction.response.send_message(
                "This action must be confirmed inside the server.", ephemeral=True
            )
        category = guild.get_channel(self.category_id)
        if not isinstance(category, discord.CategoryChannel):
            return await interaction.response.edit_message(
                content="That category no longer exists. No use was consumed.",
                view=None,
            )
        me = guild.me
        if me is None or not me.guild_permissions.manage_channels:
            return await interaction.response.edit_message(
                content="I need Manage Channels permission. No use was consumed.",
                view=None,
            )

        await interaction.response.defer(ephemeral=True, thinking=True)
        claimed, used = await database.claim_category_removal(guild.id, limit=3)
        if not claimed:
            return await interaction.followup.send(
                f"This server has used all 3 category removals. Usage: {used}/3.",
                ephemeral=True,
            )

        deleted = 0
        failures = []
        # Remove every channel in the category first, then remove the category.
        for child in list(category.channels):
            try:
                await child.delete(reason=f"Category removal requested by {interaction.user} ({interaction.user.id})")
                deleted += 1
            except (discord.Forbidden, discord.HTTPException) as exc:
                failures.append(f"{child.name}: {exc}")

        category_deleted = False
        try:
            if not failures:
                await category.delete(
                    reason=f"Category removal requested by {interaction.user} ({interaction.user.id})"
                )
                category_deleted = True
            else:
                failures.append("Category retained because one or more channels could not be deleted.")
        except (discord.Forbidden, discord.HTTPException) as exc:
            failures.append(f"Category: {exc}")

        for item in self.children:
            item.disabled = True
        result = (
            f"Deleted {deleted} channel(s). "
            f"{'Category deleted.' if category_deleted else 'Category was not deleted.'} "
            f"Server usage: {used}/3."
        )
        if failures:
            result += "\nIssues:\n" + "\n".join(failures[:8])
        await interaction.followup.send(result, ephemeral=True)
        try:
            await interaction.message.edit(view=self)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.requester_id:
            return await interaction.response.send_message(
                "Only the administrator who started this action can cancel it.",
                ephemeral=True,
            )
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="Category removal cancelled. No use was consumed.",
            view=self,
        )


class CategoryTools(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="remove_category",
        description="Permanently delete a category and all channels inside it (3 uses per server).",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def remove_category(
        self,
        interaction: discord.Interaction,
        category: discord.CategoryChannel,
    ):
        guild = interaction.guild
        if guild is None:
            return await interaction.response.send_message(
                "Use this command inside a server.", ephemeral=True
            )
        if category.guild.id != guild.id:
            return await interaction.response.send_message(
                "Choose a category from this server.", ephemeral=True
            )
        me = guild.me
        if me is None or not me.guild_permissions.manage_channels:
            return await interaction.response.send_message(
                "I need Manage Channels permission to do this.", ephemeral=True
            )
        used = await database.category_removal_uses(guild.id)
        if used >= 3:
            return await interaction.response.send_message(
                "This server has used all 3 category removals. Usage: 3/3.",
                ephemeral=True,
            )

        embed = discord.Embed(
            title="Confirm permanent category removal",
            description=(
                f"**Category:** {category.name}\n"
                f"**Channels inside:** {len(category.channels)}\n\n"
                "Confirming will permanently delete every channel inside this category, "
                "then delete the category itself. Deleted channels and their messages cannot "
                "be restored by this bot.\n\n"
                f"**Remaining uses:** {3 - used}/3"
            ),
            color=discord.Color.red(),
        )
        await interaction.response.send_message(
            embed=embed,
            view=ConfirmCategoryRemoval(self.bot, category.id, interaction.user.id),
            ephemeral=True,
        )

    @app_commands.command(
        name="category_removal_uses",
        description="Check how many category removals this server has used.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def category_removal_uses(self, interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message(
                "Use this command inside a server.", ephemeral=True
            )
        used = await database.category_removal_uses(interaction.guild.id)
        await interaction.response.send_message(
            f"Category removals used: **{used}/3**. Remaining: **{3 - used}/3**.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(CategoryTools(bot))
