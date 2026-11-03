import re
import discord
from discord import app_commands
from discord.ext import commands
import database

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

async def _get_category(guild, cfg, kind):
    key = "renewal_category_id" if kind == "renewal" else "ticket_category_id"
    category = guild.get_channel(cfg[key]) if cfg.get(key) else None
    if not isinstance(category, discord.CategoryChannel):
        category = await guild.create_category("Renewal Tickets" if kind == "renewal" else "Mentorship Tickets")
        await database.set_config(guild.id, **{key: category.id})
    if len(category.channels) >= 49:
        category = await guild.create_category(f"{category.name} - Part 2")
        await database.set_config(guild.id, **{key: category.id})
    return category

async def create_private_ticket(guild, member_or_user, cfg, kind):
    category = await _get_category(guild, cfg, kind)
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        member_or_user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
    }
    if guild.me:
        overwrites[guild.me] = discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)
    channel = await guild.create_text_channel(
        name=f"{kind}-{member_or_user.id}"[:90], category=category,
        overwrites=overwrites, reason=f"{kind} ticket")
    await database.add_ticket(channel.id, guild.id, member_or_user.id, kind)
    await channel.send(
        f"{member_or_user.mention if isinstance(member_or_user, discord.Member) else str(member_or_user)} "
        "Please provide the email address used for your Whop/payment purchase. "
        "A staff member must verify the payment before granting access.")
    return channel

class PurchasePanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Purchase Mentorship", style=discord.ButtonStyle.primary,
                       custom_id="reveals:mentorship_purchase")
    async def purchase(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = await database.get_config(interaction.guild_id)
        if not cfg:
            return await interaction.response.send_message("An administrator must run /setup first.", ephemeral=True)
        channel = await create_private_ticket(interaction.guild, interaction.user, cfg, "purchase")
        await interaction.response.send_message(f"Your private ticket: {channel.mention}", ephemeral=True)

class Ticketing(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.add_view(PurchasePanel())

    @app_commands.command(name="mentorship_panel", description="Post the mentorship purchase panel.")
    @app_commands.checks.has_permissions(administrator=True)
    async def mentorship_panel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        cfg = await database.get_config(interaction.guild_id)
        if not cfg:
            return await interaction.response.send_message("Run /setup first.", ephemeral=True)
        if channel.guild.id != cfg["server_a_id"]:
            return await interaction.response.send_message("Select a Server A channel.", ephemeral=True)
        message = await channel.send(
            "**Mentorship**\nClick the button below to open a private purchase ticket.",
            view=PurchasePanel())
        await database.set_config(interaction.guild_id,
            panel_channel_id=channel.id, panel_message_id=message.id)
        await interaction.response.send_message("Purchase panel posted.", ephemeral=True)

    @app_commands.command(name="verify_purchase", description="Staff: verify payment email and issue a one-use invite.")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def verify_purchase(self, interaction: discord.Interaction, email: str):
        ticket = await database.get_ticket(interaction.channel_id)
        if not ticket or ticket["guild_id"] != interaction.guild_id:
            return await interaction.response.send_message("This channel is not a registered ticket.", ephemeral=True)
        if not EMAIL_RE.fullmatch(email):
            return await interaction.response.send_message("Enter a valid payment email.", ephemeral=True)
        cfg = await database.get_config(ticket["guild_id"])
        community = self.bot.get_guild(cfg["server_b_id"])
        if community is None:
            return await interaction.response.send_message("Server B is unavailable.", ephemeral=True)
        invite_channel = next((c for c in community.text_channels
            if c.permissions_for(community.me).create_instant_invite), None)
        if invite_channel is None:
            return await interaction.response.send_message("The bot cannot create invites in Server B.", ephemeral=True)
        invite = await invite_channel.create_invite(max_uses=1, max_age=86400,
            unique=True, reason=f"Verified mentorship purchase by {interaction.user}")
        await database.verify_ticket(interaction.channel_id, email)
        await database.save_subscription(ticket["user_id"], cfg["server_a_id"], cfg["subscription_days"])
        try:
            user = await self.bot.fetch_user(ticket["user_id"])
            await user.send(f"Your verified mentorship invite (one use, expires in 24 hours): {invite.url}")
        except discord.HTTPException:
            await interaction.channel.send(f"Student invite: {invite.url}")
        await interaction.response.send_message("Email recorded and one-time invite generated. Confirm the payment independently before using this command.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Ticketing(bot))
