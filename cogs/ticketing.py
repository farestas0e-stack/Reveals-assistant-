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


async def create_private_ticket(guild: discord.Guild, member_or_user, cfg: dict,
                                kind: str, submitted_email: str | None = None):
    existing_id = await database.find_open_ticket(guild.id, member_or_user.id, kind)
    if existing_id:
        existing = guild.get_channel(existing_id)
        if existing:
            if submitted_email:
                await database.set_ticket_email(existing_id, submitted_email)
                await existing.send(f"Updated payment email submitted: **{submitted_email}**")
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
    channel = await guild.create_text_channel(
        name=f"{kind}-{member_or_user.id}"[:90], category=category,
        overwrites=overwrites, reason=f"{kind} ticket")
    await database.add_ticket(channel.id, guild.id, member_or_user.id, kind)
    if submitted_email:
        await database.set_ticket_email(channel.id, submitted_email)
    title = "Membership purchase ticket" if kind == "purchase" else "Membership renewal ticket"
    embed = discord.Embed(
        title=title,
        description=f"{member_or_user.mention}, this private ticket is open. Use the button below when your request is complete.",
        color=discord.Color.blurple())
    if submitted_email:
        embed.add_field(name="Payment email", value=submitted_email, inline=False)
    embed.add_field(name="Next step", value="Use **Buy Membership** below to open the checkout page. Staff will verify payment before access is granted.", inline=False)
    await channel.send(embed=embed, view=TicketControls(cfg.get("renewal_url")))
    return channel


class PurchaseEmailModal(discord.ui.Modal, title="Purchase Mentorship"):
    payment_email = discord.ui.TextInput(
        label="Whop / payment email address",
        placeholder="you@example.com",
        required=True,
        max_length=254)

    async def on_submit(self, interaction: discord.Interaction):
        email = str(self.payment_email).strip()
        if not EMAIL_RE.fullmatch(email):
            return await interaction.response.send_message(
                "Please enter a valid email address.", ephemeral=True)
        if interaction.guild is None:
            return await interaction.response.send_message(
                "Use this form in Server A.", ephemeral=True)
        cfg = await database.get_config(interaction.guild_id)
        if not cfg:
            return await interaction.response.send_message(
                "An administrator must run /setup first.", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            channel = await create_private_ticket(
                interaction.guild, interaction.user, cfg, "purchase", email)
        except (discord.Forbidden, discord.HTTPException):
            return await interaction.followup.send(
                "I couldn't create your ticket. Please contact staff.", ephemeral=True)
        await interaction.followup.send(
            f"Your private purchase ticket is ready: {channel.mention}", ephemeral=True)


class PurchasePanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Purchase Mentorship", style=discord.ButtonStyle.primary,
                       custom_id="reveals:mentorship_purchase")
    async def purchase(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild is None:
            return await interaction.response.send_message(
                "Use this button in Server A.", ephemeral=True)
        cfg = await database.get_config(interaction.guild_id)
        if not cfg:
            return await interaction.response.send_message(
                "An administrator must run /setup first.", ephemeral=True)
        await interaction.response.send_modal(PurchaseEmailModal())


class DynamicCloseButton(discord.ui.DynamicItem[discord.ui.Button], template=r"reveals:close_ticket"):
    def __init__(self):
        super().__init__(discord.ui.Button(
            label="Close ticket", style=discord.ButtonStyle.danger,
            emoji="🔒", custom_id="reveals:close_ticket"))

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction,
                             item: discord.ui.Button, match):
        return cls()

    async def callback(self, interaction: discord.Interaction):
        ticket = await database.get_ticket(interaction.channel_id)
        if not ticket or ticket["guild_id"] != interaction.guild_id:
            return await interaction.response.send_message("This is not a registered ticket.", ephemeral=True)
        is_owner = interaction.user.id == ticket["user_id"]
        is_staff = interaction.user.guild_permissions.manage_channels or interaction.user.guild_permissions.administrator
        if not (is_owner or is_staff):
            return await interaction.response.send_message("Only the ticket owner or staff can close this ticket.", ephemeral=True)
        await database.close_ticket(interaction.channel_id)
        await interaction.response.send_message("Ticket closed. This channel will now be deleted.")
        await interaction.channel.delete(reason=f"Ticket closed by {interaction.user}")


class TicketControls(discord.ui.View):
    def __init__(self, membership_url: str | None):
        super().__init__(timeout=None)
        if membership_url and membership_url.startswith(("https://", "http://")):
            self.add_item(discord.ui.Button(
                label="Buy Membership", style=discord.ButtonStyle.link, url=membership_url))
        self.add_item(DynamicCloseButton())


class Ticketing(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.add_view(PurchasePanel())
        self.bot.add_dynamic_items(DynamicCloseButton)

    @app_commands.command(name="mentorship_panel", description="Post the mentorship purchase panel.")
    @app_commands.checks.has_permissions(administrator=True)
    async def mentorship_panel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        cfg = await database.get_config(interaction.guild_id)
        if not cfg:
            return await interaction.response.send_message("Run /setup first.", ephemeral=True)
        if channel.guild.id != cfg["server_a_id"]:
            return await interaction.response.send_message("Select a Server A channel.", ephemeral=True)
        panel = discord.Embed(
            title="Mentorship Membership",
            description="Ready to join? Click **Purchase Mentorship** below to open a private ticket and submit your payment email.",
            color=discord.Color.blurple())
        message = await channel.send(embed=panel, view=PurchasePanel())
        await database.set_config(interaction.guild_id,
                                  panel_channel_id=channel.id, panel_message_id=message.id)
        await interaction.response.send_message("Purchase panel posted.", ephemeral=True)

    @app_commands.command(name="approve_purchase",
                          description="Approve only after independently confirming payment.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(email="Email verified against the payment receipt")
    async def approve_purchase(self, interaction: discord.Interaction, email: str):
        if interaction.guild is None:
            return await interaction.response.send_message(
                "Use this command inside the purchase ticket.", ephemeral=True)
        ticket = await database.get_ticket(interaction.channel_id)
        if not ticket or ticket["guild_id"] != interaction.guild_id:
            return await interaction.response.send_message(
                "This is not a registered ticket.", ephemeral=True)
        if ticket["ticket_type"] not in ("purchase", "renewal"):
            return await interaction.response.send_message(
                "Only purchase or renewal tickets can be approved.", ephemeral=True)
        if ticket["approved_at"]:
            return await interaction.response.send_message(
                "This ticket has already been approved.", ephemeral=True)
        if not EMAIL_RE.fullmatch(email):
            return await interaction.response.send_message(
                "Enter a valid payment email.", ephemeral=True)
        submitted = ticket.get("submitted_email")
        if submitted and submitted.casefold() != email.strip().casefold():
            return await interaction.response.send_message(
                f"The verified receipt email does not match the submitted email ({submitted}). "
                "Check the payment record before approving.", ephemeral=True)
        cfg = await database.get_config(ticket["guild_id"])
        if not cfg:
            return await interaction.response.send_message(
                "Server configuration is missing.", ephemeral=True)
        community = self.bot.get_guild(cfg["server_b_id"])
        if community is None or community.me is None:
            return await interaction.response.send_message(
                "Server B is unavailable.", ephemeral=True)
        role = interaction.guild.get_role(cfg["mentorship_role_id"])
        if role is None:
            return await interaction.response.send_message(
                "The configured mentorship role no longer exists.", ephemeral=True)
        try:
            member = interaction.guild.get_member(ticket["user_id"]) or await interaction.guild.fetch_member(ticket["user_id"])
        except discord.NotFound:
            return await interaction.response.send_message(
                "The student must join Server A before approval.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        try:
            # This is the manual-payment fallback. Adding the configured role
            # triggers the same invite workflow as Superprofile role assignment.
            await database.set_ticket_email(interaction.channel_id, email.strip())
            if role not in member.roles:
                await member.add_roles(
                    role, reason=f"Payment verified and approved by Administrator {interaction.user.id}")
                result = "Mentorship role assigned. The role-assignment event will deliver the Server B invite."
            else:
                result = "The mentorship role is already assigned. If Superprofile assigned it, the role event has already initiated access delivery."
            await database.save_subscription(
                ticket["user_id"], cfg["server_a_id"], cfg["subscription_days"])
            await database.approve_ticket(interaction.channel_id)
            await interaction.channel.send(
                f"✅ Payment approved by Administrator {interaction.user.mention}. {result}")
            await interaction.followup.send(
                f"Purchase approved. {result}", ephemeral=True)
        except (discord.HTTPException, discord.Forbidden):
            await interaction.followup.send(
                "Approval failed. Check bot permissions and role hierarchy, then retry.",
                ephemeral=True)
            raise

    @app_commands.command(name="close_ticket", description="Close and delete this ticket.")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def close_ticket_command(self, interaction: discord.Interaction):
        ticket = await database.get_ticket(interaction.channel_id)
        if not ticket or ticket["guild_id"] != interaction.guild_id:
            return await interaction.response.send_message(
                "This is not a registered ticket.", ephemeral=True)
        await database.close_ticket(interaction.channel_id)
        await interaction.response.send_message("Closing ticket…", ephemeral=True)
        await interaction.channel.delete(reason=f"Ticket closed by {interaction.user}")


async def setup(bot):
    await bot.add_cog(Ticketing(bot))
