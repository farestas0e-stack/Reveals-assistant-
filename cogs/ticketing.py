import re
import io
import logging
import discord
from discord import app_commands
from discord.ext import commands
import database

log = logging.getLogger("reveals-assistant.ticketing")

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif")

async def _get_category(guild: discord.Guild, cfg: dict, kind: str):
    key = "renewal_category_id" if kind == "renewal" else "ticket_category_id"
    prefix = "Renewal Tickets" if kind == "renewal" else "Mentorship Tickets"
    category = guild.get_channel(cfg.get(key)) if cfg.get(key) else None
    if not isinstance(category, discord.CategoryChannel):
        category = await guild.create_category(prefix)
        await database.set_config(guild.id, **{key: category.id})
    if len(category.channels) >= 49:
        parts = sum(1 for item in guild.categories if item.name.startswith(prefix))
        category = await guild.create_category(f"{prefix} - Part {parts + 1}")
        await database.set_config(guild.id, **{key: category.id})
    return category

async def create_private_ticket(guild: discord.Guild, member: discord.Member,
                                cfg: dict, kind: str,
                                submitted_email: str | None = None):
    if not isinstance(member, discord.Member) or member.guild.id != guild.id:
        raise ValueError("A ticket owner must be a current member of the server.")
    existing_id = await database.find_open_ticket(guild.id, member.id, kind)
    if existing_id:
        existing = guild.get_channel(existing_id)
        if isinstance(existing, discord.TextChannel):
            return existing
    category = await _get_category(guild, cfg, kind)
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        member: discord.PermissionOverwrite(view_channel=True, send_messages=True,
            read_message_history=True, attach_files=True, embed_links=True)
    }
    if guild.me:
        overwrites[guild.me] = discord.PermissionOverwrite(view_channel=True,
            send_messages=True, manage_channels=True, read_message_history=True)
    staff_role = guild.get_role(cfg.get("staff_role_id")) if cfg.get("staff_role_id") else None
    if staff_role:
        overwrites[staff_role] = discord.PermissionOverwrite(view_channel=True,
            send_messages=True, read_message_history=True, manage_messages=True)
    for role in guild.roles:
        if role.permissions.administrator:
            overwrites[role] = discord.PermissionOverwrite(view_channel=True,
                send_messages=True, read_message_history=True, manage_messages=True)
    channel = await guild.create_text_channel(
        name=f"{kind}-{re.sub(r'[^a-z0-9-]+', '-', member.display_name.lower()).strip('-') or 'member'}"[:90], category=category, overwrites=overwrites,
        reason=f"{kind} ticket for {member.id}"
    )
    await database.add_ticket(channel.id, guild.id, member.id, kind, submitted_email)
    welcome = discord.Embed(
        title="JOIN THE REVEALS CIRCLE",
        description=(
            "A step-by-step mentorship to take you from zero to your first $1,000 in clipping, "
            "and the system to keep scaling after that.\n\n"
            "Built from 3 years of real clipping experience, with the mistakes, lessons, "
            "and methods that actually work."
        ),
        color=discord.Color.blurple()
    )
    welcome.add_field(
        name="🎯 What You Get",
        value=(
            "• Full roadmap in step-by-step video modules\n"
            "• 1 exclusive webinar every month\n"
            "• 1 live Q&A session every month\n"
            "• Clip reviews\n"
            "• Private Discord server for members\n"
            "• Direct access to experienced clippers in the community\n"
            "• First access to Om's future campaigns and client work"
        ),
        inline=False
    )
    welcome.add_field(
        name="📚 Inside the Course",
        value=(
            "• Viral Clip Editing Tutorials with Formats\n"
            "• Proper Account Setup & Warm Up\n"
            "• How to Avoid Bans & Protect Your Accounts\n"
            "• Virality, Views & Analytics Explained\n"
            "• Tier 1 Audience Reach Methods\n"
            "• How to Escape 0 View Jail\n"
            "• Proven Methods for Different Platforms\n"
            "• Clipping Platforms Explained\n"
            "• How to Get Your First Payout\n"
            "• Scaling with Multiple Accounts & Systems\n"
            "• Turning Clipping into a Sustainable Income Source\n"
            "• Mindset + Longevity in the Clipping Game"
        ),
        inline=False
    )
    welcome.add_field(
        name="🎁 Bonuses",
        value=(
            "• Curated Asset Packs (Presets, SFX, Overlays)\n"
            "• Exclusive Tool Deals (VPN, AI Clipper & More)\n"
            "• Regular Campaign Opportunity Updates"
        ),
        inline=False
    )
    welcome.add_field(name="Discord member", value=f"{member.display_name} ({member.mention})", inline=False)
    if submitted_email:
        welcome.add_field(name="Payment email", value=submitted_email, inline=False)
    welcome.set_footer(text="Reveals Circle • Membership support")
    await channel.send(embed=welcome)

    instructions = discord.Embed(
        title="Your private mentorship ticket",
        description=(
            f"{member.mention}, use the button below to open the membership checkout link. "
            "After completing payment, your configured membership role will be assigned "
            "automatically and Server B access will be delivered."
        ),
        color=discord.Color.dark_teal()
    )
    if cfg.get("renewal_url") or cfg.get("monthly_url"):
        instructions.add_field(
            name="Checkout",
            value="Select **Get membership link** below. Keep this ticket open until your access is delivered.",
            inline=False
        )
    await channel.send(embed=instructions, view=PurchaseTierView())


async def _ticket_transcript(channel: discord.TextChannel) -> tuple[bytes, int, bool]:
    lines = [
        f"Ticket transcript: #{channel.name}",
        f"Guild: {channel.guild.name} ({channel.guild.id})",
        f"Channel ID: {channel.id}",
        "=" * 72,
        ""
    ]
    count = 0
    truncated = False
    async for message in channel.history(limit=None, oldest_first=True):
        count += 1
        timestamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")
        author = f"{message.author} ({message.author.id})"
        lines.append(f"[{timestamp}] {author}")
        if message.content:
            lines.append(message.clean_content)
        for embed in message.embeds:
            if embed.title:
                lines.append(f"[Embed title] {embed.title}")
            if embed.description:
                lines.append(f"[Embed description] {embed.description}")
            for field in embed.fields:
                lines.append(f"[{field.name}] {field.value}")
        for attachment in message.attachments:
            lines.append(f"[Attachment: {attachment.filename}] {attachment.url}")
        if message.stickers:
            lines.append("[Sticker] " + ", ".join(sticker.name for sticker in message.stickers))
        lines.append("")
        if sum(len(line) + 1 for line in lines) > 1_500_000:
            truncated = True
            lines.append("[Transcript truncated to remain within Discord upload limits.]")
            break
    if count == 0:
        lines.append("No messages were found in this ticket.")
    return "\n".join(lines).encode("utf-8", errors="replace"), count, truncated


async def _prompt_ticket_close(interaction: discord.Interaction, ticket: dict):
    embed = discord.Embed(
        title="Confirm ticket closure",
        description=(
            "This action will create a transcript, send the ticket details and transcript "
            "together as **one log message**, then delete this ticket channel.\n\n"
            "**Are you sure you want to close this ticket?**"
        ),
        color=discord.Color.orange()
    )
    await interaction.response.send_message(
        embed=embed,
        view=ConfirmTicketCloseView(interaction.user.id),
        ephemeral=True
    )


async def _complete_ticket_close(interaction: discord.Interaction, requester_id: int):
    if interaction.user.id != requester_id:
        return await interaction.response.send_message(
            "Only the person who requested closure can confirm it.", ephemeral=True
        )
    ticket = await database.get_ticket(interaction.channel_id)
    if not ticket or ticket["guild_id"] != interaction.guild_id:
        return await interaction.response.send_message("Not a registered ticket.", ephemeral=True)
    is_owner = ticket["user_id"] == interaction.user.id
    can_manage = (
        interaction.user.guild_permissions.manage_channels
        or interaction.user.guild_permissions.administrator
    )
    if not is_owner and not can_manage:
        return await interaction.response.send_message(
            "Only the ticket owner or staff can close this ticket.", ephemeral=True
        )
    channel = interaction.channel
    if not isinstance(channel, discord.TextChannel):
        return await interaction.response.send_message("Ticket channel is unavailable.", ephemeral=True)
    cfg = await database.get_config(ticket["guild_id"])
    log_channel = channel.guild.get_channel(cfg.get("ticket_log_channel_id")) if cfg else None
    if not isinstance(log_channel, discord.TextChannel):
        return await interaction.response.send_message(
            "Ticket logging is not configured. An administrator must set the Ticket logs / transcripts channel in /setup. The ticket has not been closed.",
            ephemeral=True
        )

    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        transcript, message_count, truncated = await _ticket_transcript(channel)
        owner = channel.guild.get_member(ticket["user_id"])
        owner_label = f"{owner} ({ticket['user_id']})" if owner else f"User ID {ticket['user_id']}"
        closed_embed = discord.Embed(
            title="Ticket closed",
            description=(
                f"**Ticket:** #{channel.name}\n"
                f"**Ticket type:** {ticket['ticket_type'].title()}\n"
                f"**Opened by:** {owner_label}\n"
                f"**Closed by:** {interaction.user.mention} ({interaction.user.id})\n"
                f"**Payment email:** {ticket.get('submitted_email') or 'Not provided'}\n"
                f"**Messages captured:** {message_count}\n"
                f"**Transcript:** {'Truncated to fit upload limits' if truncated else 'Complete'}"
            ),
            color=discord.Color.dark_grey(),
            timestamp=discord.utils.utcnow()
        )
        closed_embed.set_footer(text=f"Ticket channel ID: {channel.id}")
        transcript_file = discord.File(
            io.BytesIO(transcript),
            filename=f"ticket-{channel.id}-transcript.txt"
        )
        await log_channel.send(embed=closed_embed, file=transcript_file)
    except (discord.HTTPException, OSError):
        log.exception("Could not save transcript for ticket %s", channel.id)
        return await interaction.followup.send(
            "The transcript could not be sent to the ticket log channel. The ticket has been left open.",
            ephemeral=True
        )

    await database.close_ticket(channel.id)
    try:
        await channel.delete(reason=f"Ticket closed by {interaction.user.id}; transcript saved")
    except discord.HTTPException:
        log.exception("Transcript saved, but ticket channel %s could not be deleted", channel.id)
        return await interaction.followup.send(
            "The transcript was saved, but Discord could not delete the ticket channel. Staff can delete it manually.",
            ephemeral=True
        )
    await interaction.followup.send(
        "Ticket transcript saved and ticket closed successfully.", ephemeral=True
    )


class ConfirmTicketCloseView(discord.ui.View):
    def __init__(self, requester_id: int):
        super().__init__(timeout=90)
        self.requester_id = requester_id

    @discord.ui.button(label="Confirm close", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _complete_ticket_close(interaction, self.requester_id)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.requester_id:
            return await interaction.response.send_message(
                "Only the person who requested closure can cancel it.", ephemeral=True
            )
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="Ticket closure cancelled. The ticket remains open.",
            embed=None, view=self
        )

class PurchaseEmailModal(discord.ui.Modal, title="Purchase Mentorship"):
    payment_email = discord.ui.TextInput(
        label="Whop / payment email address",
        placeholder="you@example.com", required=True, max_length=254
    )

    async def on_submit(self, interaction: discord.Interaction):
        email = str(self.payment_email).strip()
        if not EMAIL_RE.fullmatch(email):
            return await interaction.response.send_message(
                "Enter a valid email address.", ephemeral=True
            )
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message(
                "Use this in Server A.", ephemeral=True
            )
        cfg = await database.get_config(interaction.guild_id)
        if not cfg:
            return await interaction.response.send_message(
                "An administrator must run /setup first.", ephemeral=True
            )
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            ticket = await create_private_ticket(
                interaction.guild, interaction.user, cfg, "purchase", email
            )
            await database.set_ticket_email(ticket.id, email)
        except (discord.HTTPException, ValueError):
            return await interaction.followup.send(
                "Ticket creation failed. Contact staff.", ephemeral=True
            )
        await interaction.followup.send(f"Your private ticket: {ticket.mention}", ephemeral=True)

class PurchasePanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Purchase Mentorship", style=discord.ButtonStyle.primary,
                       custom_id="reveals:mentorship_purchase")
    async def purchase(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild:
            return await interaction.response.send_message("Use this in Server A.", ephemeral=True)
        if not await database.get_config(interaction.guild_id):
            return await interaction.response.send_message("Run /setup first.", ephemeral=True)
        await interaction.response.send_modal(PurchaseEmailModal())

class PurchaseTierView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Get membership link", style=discord.ButtonStyle.success,
                       custom_id="reveals:membership_checkout")
    async def checkout(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket = await database.get_ticket(interaction.channel_id)
        if not ticket or ticket["user_id"] != interaction.user.id:
            return await interaction.response.send_message("Only the ticket owner can request the checkout link.", ephemeral=True)
        if ticket["approval_status"] != "pending":
            return await interaction.response.send_message("This ticket is no longer pending.", ephemeral=True)
        cfg = await database.get_config(ticket["guild_id"])
        url = (cfg.get("renewal_url") or cfg.get("monthly_url")) if cfg else None
        if not url or not url.startswith(("https://", "http://")):
            return await interaction.response.send_message("The membership checkout link is not configured. Contact staff.", ephemeral=True)
        checkout_embed = discord.Embed(
            title="Membership checkout",
            description=f"Continue securely using the link below.\n\n[Open checkout]({url})",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=checkout_embed, ephemeral=True)

    @discord.ui.button(label="Close ticket", style=discord.ButtonStyle.danger,
                       custom_id="reveals:ticket_close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket = await database.get_ticket(interaction.channel_id)
        if not ticket or ticket["guild_id"] != interaction.guild_id:
            return await interaction.response.send_message("Not a registered ticket.", ephemeral=True)
        is_owner = ticket["user_id"] == interaction.user.id
        can_manage = interaction.user.guild_permissions.manage_channels or interaction.user.guild_permissions.administrator
        if not is_owner and not can_manage:
            return await interaction.response.send_message("Only the ticket owner or staff can close this ticket.", ephemeral=True)
        await _prompt_ticket_close(interaction, ticket)

class Ticketing(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        bot.add_view(PurchasePanel())
        bot.add_view(PurchaseTierView())


    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or not message.attachments:
            return
        ticket = await database.get_ticket(message.channel.id)
        if not ticket or ticket["ticket_type"] not in ("purchase", "renewal"):
            return
        images = [att for att in message.attachments if (att.content_type or "").startswith("image/") or att.filename.lower().endswith(IMAGE_EXTENSIONS)]
        if not images:
            return
        if ticket["approval_status"] == "pending":
            await database.set_evidence(message.channel.id, message.id)
        cfg = await database.get_config(message.guild.id)
        staff_role = message.guild.get_role(cfg.get("staff_role_id")) if cfg and cfg.get("staff_role_id") else None
        received_embed = discord.Embed(
            title="Payment screenshot received",
            description=(
                "Your screenshot has been forwarded to the sales log. "
                "Server B access is granted automatically when the configured membership role is assigned."
            ),
            color=discord.Color.green(),
            timestamp=message.created_at
        )
        received_embed.set_footer(text="Reveals Circle • Keep this ticket open until access is delivered")
        await message.channel.send(
            content=(staff_role.mention if staff_role else None),
            embed=received_embed,
            allowed_mentions=discord.AllowedMentions(roles=True, everyone=False)
        )
        sales_log = message.guild.get_channel(cfg.get("sales_channel_id")) if cfg and cfg.get("sales_channel_id") else None
        if isinstance(sales_log, discord.TextChannel):
            try:
                screenshot = images[0]
                screenshot_file = await screenshot.to_file()
                sales_embed = discord.Embed(
                    title="Payment screenshot submitted",
                    description=(
                        f"**Submitted by:** {message.author.mention}\n"
                        f"**Username:** {discord.utils.escape_markdown(str(message.author))}\n"
                        f"**User ID:** {message.author.id}"
                    ),
                    color=discord.Color.blurple(),
                    timestamp=message.created_at
                )
                sales_embed.set_thumbnail(url=message.author.display_avatar.url)
                sales_embed.set_image(url=f"attachment://{screenshot.filename}")
                await sales_log.send(embed=sales_embed, file=screenshot_file)
            except discord.HTTPException:
                log.exception("Could not forward payment screenshot to the sales channel")

    @app_commands.command(name="mentorship_panel", description="Post the purchase panel.")
    @app_commands.checks.has_permissions(administrator=True)
    async def mentorship_panel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        cfg = await database.get_config(interaction.guild_id)
        if not cfg:
            return await interaction.response.send_message("Run /setup first.", ephemeral=True)
        embed = discord.Embed(
            title="Mentorship Membership",
            description="Click Purchase Mentorship, enter your payment email, and follow the instructions in your private ticket.",
            color=discord.Color.blurple()
        )
        message = await channel.send(embed=embed, view=PurchasePanel())
        await database.set_config(interaction.guild_id, panel_channel_id=channel.id, panel_message_id=message.id)
        await interaction.response.send_message("Purchase panel posted.", ephemeral=True)

    @app_commands.command(name="membership_status", description="Check role-based membership access.")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def membership_status(self, interaction: discord.Interaction, member: discord.Member):
        cfg = await database.get_config(interaction.guild_id)
        role = interaction.guild.get_role(cfg.get("mentorship_role_id")) if cfg else None
        if role is None:
            return await interaction.response.send_message("The membership role is not configured.", ephemeral=True)
        active = role in member.roles
        status = "Active — membership role is assigned" if active else "Inactive — membership role is not assigned"
        await interaction.response.send_message(
            f"{member} ({member.id}) — {status}. No expiry is calculated by this bot.",
            ephemeral=True
        )

    @app_commands.command(name="close_ticket", description="Close and delete this ticket.")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def close_ticket_command(self, interaction: discord.Interaction):
        ticket = await database.get_ticket(interaction.channel_id)
        if not ticket or ticket["guild_id"] != interaction.guild_id:
            return await interaction.response.send_message("Not a registered ticket.", ephemeral=True)
        await _prompt_ticket_close(interaction, ticket)

async def setup(bot):
    await bot.add_cog(Ticketing(bot))
