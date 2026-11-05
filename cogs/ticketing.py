import re
import discord
from discord import app_commands
from discord.ext import commands
import database

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
        name=f"{kind}-{member.id}"[:90], category=category, overwrites=overwrites,
        reason=f"{kind} ticket for {member.id}"
    )
    await database.add_ticket(channel.id, guild.id, member.id, kind, submitted_email)
    title = "Membership purchase ticket" if kind == "purchase" else "Membership renewal ticket"
    embed = discord.Embed(
        title=title,
        description=(f"{member.mention}, use the button below to get the membership checkout link. Complete payment, then "
                     "upload your receipt if requested. Server B access is granted automatically when "
                     "the configured membership role is assigned."),
        color=discord.Color.blurple()
    )
    embed.add_field(name="Discord user", value=f"{member} ({member.id})", inline=False)
    if submitted_email:
        embed.add_field(name="Payment email", value=submitted_email, inline=False)
    cfg_url = cfg.get("renewal_url") or cfg.get("monthly_url")
    if cfg_url:
        embed.add_field(name="Checkout", value="Use the Get membership link button below.", inline=False)
    await channel.send(embed=embed, view=PurchaseTierView())
    return channel

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
        await interaction.response.send_message(f"Membership checkout link: {url}", ephemeral=True)

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
        await database.close_ticket(interaction.channel_id)
        await interaction.response.send_message("Ticket closed. This channel will now be deleted.", ephemeral=True)
        await interaction.channel.delete(reason=f"Ticket closed by {interaction.user.id}")

class CloseTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

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
        await database.close_ticket(interaction.channel_id)
        await interaction.response.send_message("Ticket closed. This channel will now be deleted.", ephemeral=True)
        await interaction.channel.delete(reason=f"Ticket closed by {interaction.user.id}")

class EvidenceReviewView(discord.ui.View):
    async def approve_from_role_log(self, interaction: discord.Interaction, user_id: int, days: int):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Only Administrators can verify purchases.", ephemeral=True)
        if not interaction.guild:
            return await interaction.response.send_message("Use this inside Server A.", ephemeral=True)
        if days not in (30, 90):
            return await interaction.response.send_message("Invalid membership duration.", ephemeral=True)
        ticket = await database.find_pending_ticket(interaction.guild.id, user_id)
        if not ticket or not ticket.get("evidence_message_id"):
            return await interaction.response.send_message("No pending payment screenshot was found. Ask the member to submit it in their private ticket first.", ephemeral=True)
        cfg = await database.get_config(interaction.guild.id)
        role = interaction.guild.get_role(cfg.get("mentorship_role_id")) if cfg else None
        member = interaction.guild.get_member(user_id)
        if member is None:
            try:
                member = await interaction.guild.fetch_member(user_id)
            except discord.NotFound:
                return await interaction.response.send_message("Member is no longer in Server A.", ephemeral=True)
            except discord.HTTPException:
                return await interaction.response.send_message("Could not fetch the member. Try again.", ephemeral=True)
        if role is None or role not in member.roles:
            return await interaction.response.send_message("The configured role has not been assigned yet. Role assignment is handled automatically outside the bot.", ephemeral=True)
        community = interaction.client.get_guild(cfg.get("server_b_id")) if cfg else None
        if community is None:
            return await interaction.response.send_message("Server B is unavailable to the bot.", ephemeral=True)
        invite_channel = next((ch for ch in community.text_channels if community.me and ch.permissions_for(community.me).create_instant_invite), None)
        if invite_channel is None:
            return await interaction.response.send_message("The bot needs Create Invite permission in a Server B text channel.", ephemeral=True)
        if not await database.claim_ticket_review(ticket["channel_id"]):
            return await interaction.response.send_message("This purchase is already being reviewed or has been processed.", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        invite = None
        tenure = f"{days} days"
        try:
            await database.save_subscription(member.id, interaction.guild.id, days, tenure, ticket.get("submitted_email"))
            invite = await invite_channel.create_invite(max_uses=1, max_age=86400, unique=True, reason=f"{days}-day purchase approved by {interaction.user.id} for {member.id}")
            await database.finish_ticket_approval(ticket["channel_id"], ticket.get("submitted_email") or "", tenure)
        except Exception as exc:
            await database.release_ticket_review(ticket["channel_id"])
            if invite:
                try:
                    await invite.delete(reason="Purchase approval did not complete")
                except discord.HTTPException:
                    pass
            await interaction.followup.send(f"Approval could not finish. The purchase remains pending. Details: {type(exc).__name__}", ephemeral=True)
            raise
        delivery = f"Your purchase has been verified and your {days}-day membership is approved. Join Server B with this one-use invite (expires in 24 hours): {invite.url}"
        delivered = False
        try:
            await member.send(delivery)
            delivered = True
        except discord.HTTPException:
            ticket_channel = interaction.guild.get_channel(ticket["channel_id"])
            if isinstance(ticket_channel, discord.TextChannel):
                try:
                    await ticket_channel.send(f"{member.mention} {delivery}")
                    delivered = True
                except discord.HTTPException:
                    pass
        try:
            embed = discord.Embed.from_dict(interaction.message.embeds[0].to_dict()) if interaction.message.embeds else discord.Embed()
            embed.title = "Mentorship role assigned — purchase verified"
            duration_index = next((i for i, field in enumerate(embed.fields) if field.name == "Access duration"), None)
            if duration_index is None:
                embed.add_field(name="Access duration", value=tenure, inline=True)
            else:
                embed.set_field_at(duration_index, name="Access duration", value=tenure, inline=True)
            embed.add_field(name="Purchase verified by", value=interaction.user.mention, inline=True)
            embed.color = discord.Color.green()
            await interaction.message.edit(embed=embed, content="Purchase verified. " + ("One-use invite delivered." if delivered else "Invite delivery needs staff follow-up."), view=LogActionsView(member.id, interaction.guild.id))
        except (discord.HTTPException, IndexError):
            pass
        if delivered:
            await interaction.followup.send(f"Purchase verified for {days} days. One-use Server B invite sent.", ephemeral=True)
        else:
            await interaction.followup.send(f"Purchase verified for {days} days, but delivery failed. Send this one-use invite: {invite.url}", ephemeral=True)


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
        await message.channel.send(
            (f"{staff_role.mention} " if staff_role else "") +
            "Payment screenshot received and forwarded to the sales log. "
            "Server B access is granted automatically when the configured membership role is assigned.",
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

    @app_commands.command(name="membership_status", description="Check a member's stored membership record.")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def membership_status(self, interaction: discord.Interaction, member: discord.Member):
        sub = await database.get_subscription(member.id, interaction.guild_id)
        if not sub:
            return await interaction.response.send_message("No membership record found.", ephemeral=True)
        status = "Active" if sub["active"] else "Inactive"
        await interaction.response.send_message(
            f"{member} ({member.id}) — {status} — {sub['tenure'].title()} — "
            f"email: {sub.get('email') or 'unknown'} — expires: {sub['expires_at']}",
            ephemeral=True
        )

    @app_commands.command(name="close_ticket", description="Close and delete this ticket.")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def close_ticket_command(self, interaction: discord.Interaction):
        ticket = await database.get_ticket(interaction.channel_id)
        if not ticket or ticket["guild_id"] != interaction.guild_id:
            return await interaction.response.send_message("Not a registered ticket.", ephemeral=True)
        await database.close_ticket(interaction.channel_id)
        await interaction.response.send_message("Closing ticket.", ephemeral=True)
        await interaction.channel.delete(reason=f"Ticket closed by {interaction.user.id}")

async def setup(bot):
    await bot.add_cog(Ticketing(bot))
