import re
import discord
from discord import app_commands
from discord.ext import commands
import database

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

async def _get_category(guild: discord.Guild, cfg: dict, kind: str):
    key = "renewal_category_id" if kind == "renewal" else "ticket_category_id"
    category = guild.get_channel(cfg[key]) if cfg.get(key) else None
    prefix = "Renewal Tickets" if kind == "renewal" else "Mentorship Tickets"
    if not isinstance(category, discord.CategoryChannel):
        category = await guild.create_category(prefix)
        await database.set_config(guild.id, **{key: category.id})
    if len(category.channels) >= 49:
        existing = [c.name for c in guild.categories if c.name.startswith(prefix)]
        category = await guild.create_category(f"{prefix} - Part {len(existing) + 1}")
        await database.set_config(guild.id, **{key: category.id})
    return category

async def create_private_ticket(guild: discord.Guild, member_or_user, cfg: dict, kind: str):
    existing_id = await database.find_open_ticket(guild.id, member_or_user.id, kind)
    if existing_id:
        existing = guild.get_channel(existing_id)
        if existing:
            return existing
    category = await _get_category(guild, cfg, kind)
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        member_or_user: discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                                     read_message_history=True),
    }
    if guild.me:
        overwrites[guild.me] = discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                                            manage_channels=True, read_message_history=True)
    channel = await guild.create_text_channel(name=f"{kind}-{member_or_user.id}"[:90],
        category=category, overwrites=overwrites, reason=f"{kind} ticket")
    await database.add_ticket(channel.id, guild.id, member_or_user.id, kind)
    await channel.send(f"{member_or_user.mention} Please provide the email address used for your purchase. "
                       "A staff member will independently verify payment before approving access.")
    return channel

class PurchasePanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Purchase Mentorship", style=discord.ButtonStyle.primary,
                       custom_id="reveals:mentorship_purchase")
    async def purchase(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild is None:
            return await interaction.response.send_message("Use this button in Server A.", ephemeral=True)
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
        message = await channel.send("**Mentorship**\nClick below to open a private purchase ticket.",
                                     view=PurchasePanel())
        await database.set_config(interaction.guild_id, panel_channel_id=channel.id, panel_message_id=message.id)
        await interaction.response.send_message("Purchase panel posted.", ephemeral=True)

    @app_commands.command(name="approve_purchase", description="Approve only after independently confirming payment.")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.describe(email="Email shown on the verified payment receipt")
    async def approve_purchase(self, interaction: discord.Interaction, email: str):
        if interaction.guild is None:
            return await interaction.response.send_message("Use this command inside the purchase ticket.", ephemeral=True)
        ticket = await database.get_ticket(interaction.channel_id)
        if not ticket or ticket["guild_id"] != interaction.guild_id:
            return await interaction.response.send_message("This is not a registered ticket.", ephemeral=True)
        if ticket["ticket_type"] not in ("purchase", "renewal"):
            return await interaction.response.send_message("Only purchase or renewal tickets can be approved.", ephemeral=True)
        if ticket["approved_at"]:
            return await interaction.response.send_message("This ticket has already been approved.", ephemeral=True)
        if not EMAIL_RE.fullmatch(email):
            return await interaction.response.send_message("Enter a valid payment email.", ephemeral=True)
        cfg = await database.get_config(ticket["guild_id"])
        if not cfg:
            return await interaction.response.send_message("Server configuration is missing.", ephemeral=True)
        community = self.bot.get_guild(cfg["server_b_id"])
        if community is None or community.me is None:
            return await interaction.response.send_message("Server B is unavailable.", ephemeral=True)
        role = interaction.guild.get_role(cfg["mentorship_role_id"])
        if role is None:
            return await interaction.response.send_message("The configured mentorship role no longer exists.", ephemeral=True)
        try:
            member = interaction.guild.get_member(ticket["user_id"]) or await interaction.guild.fetch_member(ticket["user_id"])
        except discord.NotFound:
            return await interaction.response.send_message("The student must join Server A before approval.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        try:
            await database.verify_ticket(interaction.channel_id, email)
            await database.save_subscription(ticket["user_id"], cfg["server_a_id"], cfg["subscription_days"])
            if role not in member.roles:
                # The role-update listener sends the invite and creates a private ticket if DMs are closed.
                await member.add_roles(role, reason=f"Purchase manually verified by staff member {interaction.user.id}")
                delivery = "Mentorship role assigned. The bot will send the Server B invite by DM or private ticket."
            else:
                invite_channel = next((c for c in community.text_channels
                    if c.permissions_for(community.me).create_instant_invite), None)
                if invite_channel is None:
                    raise RuntimeError("Bot cannot create invites in Server B.")
                invite = await invite_channel.create_invite(max_uses=1, max_age=86400, unique=True,
                    reason=f"Manually verified purchase by staff member {interaction.user.id}")
                user = await self.bot.fetch_user(ticket["user_id"])
                try:
                    await user.send(f"Your purchase was approved. Your one-use Server B invite expires in 24 hours: {invite.url}")
                    delivery = "Invite sent by DM."
                except discord.HTTPException:
                    await interaction.channel.send(f"{user.mention} Your one-use invite expires in 24 hours: {invite.url}")
                    delivery = "DM failed; invite posted in this private ticket."
            await database.approve_ticket(interaction.channel_id)
            await interaction.followup.send(f"Purchase approved. {delivery}", ephemeral=True)
        except (discord.HTTPException, discord.Forbidden, RuntimeError):
            await interaction.followup.send("Approval failed. Check bot permissions, role hierarchy, and Server B invite permissions before retrying.", ephemeral=True)
            raise

    @app_commands.command(name="close_ticket", description="Close and delete this ticket.")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def close_ticket_command(self, interaction: discord.Interaction):
        ticket = await database.get_ticket(interaction.channel_id)
        if not ticket or ticket["guild_id"] != interaction.guild_id:
            return await interaction.response.send_message("This is not a registered ticket.", ephemeral=True)
        await database.close_ticket(interaction.channel_id)
        await interaction.response.send_message("Closing ticket…", ephemeral=True)
        await interaction.channel.delete(reason=f"Ticket closed by {interaction.user}")

async def setup(bot):
    await bot.add_cog(Ticketing(bot))
