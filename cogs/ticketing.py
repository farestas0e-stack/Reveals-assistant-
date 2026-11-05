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
        description=(f"{member.mention}, choose a plan below. Complete checkout, then "
                     "upload a clear payment receipt screenshot. Staff approval is required "
                     "before Server B access is issued."),
        color=discord.Color.blurple()
    )
    embed.add_field(name="Discord user", value=f"{member} ({member.id})", inline=False)
    if submitted_email:
        embed.add_field(name="Payment email", value=submitted_email, inline=False)
    cfg_url = cfg.get("monthly_url")
    if cfg_url:
        embed.add_field(name="Checkout", value="Use the Monthly or Quarterly button below.", inline=False)
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

    async def _send_tier(self, interaction: discord.Interaction, tenure: str):
        ticket = await database.get_ticket(interaction.channel_id)
        if not ticket or ticket["user_id"] != interaction.user.id:
            return await interaction.response.send_message(
                "Only the ticket owner can select a plan.", ephemeral=True
            )
        if ticket["approval_status"] != "pending":
            return await interaction.response.send_message(
                "This ticket is no longer pending.", ephemeral=True
            )
        cfg = await database.get_config(ticket["guild_id"])
        url = cfg.get("monthly_url" if tenure == "monthly" else "quarterly_url") if cfg else None
        if not url or not url.startswith(("https://", "http://")):
            return await interaction.response.send_message(
                "This checkout link is not configured. Contact staff.", ephemeral=True
            )
        await database.set_ticket_tenure(interaction.channel_id, tenure)
        await interaction.response.send_message(
            f"{tenure.title()} checkout link: {url}", ephemeral=True
        )

    @discord.ui.button(label="Monthly", style=discord.ButtonStyle.success,
                       custom_id="reveals:tier_monthly")
    async def monthly(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._send_tier(interaction, "monthly")

    @discord.ui.button(label="Quarterly", style=discord.ButtonStyle.primary,
                       custom_id="reveals:tier_quarterly")
    async def quarterly(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._send_tier(interaction, "quarterly")

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
    def __init__(self):
        super().__init__(timeout=None)

    async def _review(self, interaction: discord.Interaction, approve: bool):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                "Only Administrators can review payment evidence.", ephemeral=True
            )
        ticket = await database.get_ticket(interaction.channel_id)
        if not ticket or not ticket.get("evidence_message_id"):
            return await interaction.response.send_message(
                "No payment evidence is registered in this ticket.", ephemeral=True
            )
        if ticket["approval_status"] != "pending":
            return await interaction.response.send_message(
                "This evidence is already being processed or has been reviewed.", ephemeral=True
            )
        if not approve:
            changed = await database.reject_ticket(interaction.channel_id)
            if not changed:
                return await interaction.response.send_message("This ticket was already reviewed.", ephemeral=True)
            await interaction.response.edit_message(content="Payment evidence rejected by Administrator.", view=None)
            await interaction.channel.send(
                f"Payment evidence rejected by {interaction.user.mention}. Please contact staff."
            )
            return
        if ticket.get("tenure") not in ("monthly", "quarterly"):
            return await interaction.response.send_message(
                "The member must select Monthly or Quarterly before approval.", ephemeral=True
            )
        cfg = await database.get_config(ticket["guild_id"])
        guild = interaction.guild
        if not cfg or guild is None:
            return await interaction.response.send_message("Server configuration unavailable.", ephemeral=True)
        role = guild.get_role(cfg.get("mentorship_role_id"))
        community = interaction.client.get_guild(cfg.get("server_b_id"))
        if role is None or community is None:
            return await interaction.response.send_message(
                "Configured mentorship role or Server B is unavailable.", ephemeral=True
            )
        try:
            member = guild.get_member(ticket["user_id"]) or await guild.fetch_member(ticket["user_id"])
        except discord.NotFound:
            return await interaction.response.send_message("Member is no longer in Server A.", ephemeral=True)
        invite_channel = next(
            (channel for channel in community.text_channels
             if community.me and channel.permissions_for(community.me).create_instant_invite),
            None
        )
        if invite_channel is None:
            return await interaction.response.send_message(
                "The bot needs Create Invite permission in a Server B text channel.", ephemeral=True
            )
        if not await database.claim_ticket_review(interaction.channel_id):
            return await interaction.response.send_message("This ticket is already being reviewed.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        invite = None
        try:
            days = 30 if ticket["tenure"] == "monthly" else 90
            # Store the membership record before adding the role so event logs have email/tenure.
            role_was_already_present = role in member.roles
            await database.save_subscription(
                member.id, guild.id, days, ticket["tenure"], ticket.get("submitted_email")
            )
            if not role_was_already_present:
                await member.add_roles(role, reason=f"Payment approved by administrator {interaction.user.id}")
            invite = await invite_channel.create_invite(
                max_uses=1, max_age=86400, unique=True,
                reason=f"Approved membership for Discord user {member.id}"
            )
            await database.finish_ticket_approval(
                interaction.channel_id, ticket.get("submitted_email") or "", ticket["tenure"]
            )
        except Exception as exc:
            await database.release_ticket_review(interaction.channel_id)
            if invite:
                try:
                    await invite.delete(reason="Approval workflow did not complete")
                except discord.HTTPException:
                    pass
            await interaction.followup.send(
                f"Approval could not finish. The ticket remains pending; retry after fixing the issue. Details: {type(exc).__name__}",
                ephemeral=True
            )
            raise

        # The purchase is now approved. Delivery/logging failures must not roll back approval
        # or invalidate the only invite that can get the customer into Server B.
        delivery = (
            f"Your {ticket['tenure']} payment was approved. "
            f"Your one-use Server B invite (expires in 24 hours): {invite.url}"
        )
        delivered = False
        try:
            await member.send(delivery)
            delivered = True
        except discord.HTTPException:
            try:
                await interaction.channel.send(f"{member.mention} {delivery}")
                delivered = True
            except discord.HTTPException:
                pass
        try:
            await interaction.message.edit(
                content=f"Payment approved by {interaction.user.mention}. "
                        + ("Invite delivered." if delivered else "Invite delivery needs staff follow-up."),
                view=None
            )
        except discord.HTTPException:
            pass
        embed = discord.Embed(title="Sale approved", color=discord.Color.green())
        embed.add_field(name="Discord user", value=f"{member} ({member.id})", inline=False)
        embed.add_field(name="Email", value=ticket.get("submitted_email") or "Not supplied", inline=True)
        embed.add_field(name="Tenure", value=ticket["tenure"].title(), inline=True)
        # A new role assignment is logged by the role-update listener to both configured
        # role-assigned and sales channels. If the role already existed, write the sale log here.
        if role_was_already_present:
            channel = guild.get_channel(cfg.get("sales_channel_id")) if cfg.get("sales_channel_id") else None
            if isinstance(channel, discord.TextChannel):
                try:
                    await channel.send(embed=embed, view=LogActionsView(member.id, guild.id))
                except discord.HTTPException:
                    pass
        if delivered:
            await interaction.followup.send("Payment approved and one-use invite issued.", ephemeral=True)
        else:
            await interaction.followup.send(
                f"Payment approved, but automatic delivery failed. Send this one-use invite to the member: {invite.url}",
                ephemeral=True
            )

    @discord.ui.button(label="Approve Purchase", style=discord.ButtonStyle.success,
                       custom_id="reveals:evidence_approve")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._review(interaction, True)

    @discord.ui.button(label="Reject Purchase", style=discord.ButtonStyle.danger,
                       custom_id="reveals:evidence_reject")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._review(interaction, False)

class MembershipCheckButton(discord.ui.DynamicItem[discord.ui.Button],
                            template=r"reveals:membership:(?P<user_id>[0-9]{1,20})"):
    def __init__(self, user_id: int):
        self.user_id = user_id
        super().__init__(discord.ui.Button(
            label="Check membership", style=discord.ButtonStyle.secondary,
            custom_id=f"reveals:membership:{user_id}"
        ))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["user_id"]))

    async def callback(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_roles and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Staff permission required.", ephemeral=True)
        sub = await database.get_subscription(self.user_id, interaction.guild_id)
        if not sub:
            return await interaction.response.send_message("No membership record found.", ephemeral=True)
        status = "Active" if sub["active"] else "Inactive"
        await interaction.response.send_message(
            f"User ID: {self.user_id}\nStatus: {status}\nPlan: {sub['tenure'].title()}\n"
            f"Email: {sub.get('email') or 'Not recorded'}\nExpires: {sub['expires_at']}",
            ephemeral=True
        )

class ConfigStatusButton(discord.ui.DynamicItem[discord.ui.Button],
                            template=r"reveals:config:(?P<guild_id>[0-9]{1,20})"):
    def __init__(self, guild_id: int):
        self.guild_id = guild_id
        super().__init__(discord.ui.Button(
            label="Configuration status", style=discord.ButtonStyle.primary,
            custom_id=f"reveals:config:{guild_id}"
        ))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["guild_id"]))

    async def callback(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Administrator permission required.", ephemeral=True)
        cfg = await database.get_config(self.guild_id)
        if not cfg:
            return await interaction.response.send_message("No setup configuration found.", ephemeral=True)
        required = ("server_b_id", "mentorship_role_id", "sales_channel_id",
                    "role_assigned_channel_id", "role_revoked_channel_id",
                    "ticket_category_id", "renewal_category_id", "monthly_url", "quarterly_url")
        missing = [key for key in required if not cfg.get(key)]
        await interaction.response.send_message(
            "Configuration: " + ("Complete" if not missing else "Missing " + ", ".join(missing)),
            ephemeral=True
        )

class LogActionsView(discord.ui.View):
    def __init__(self, user_id: int, guild_id: int):
        super().__init__(timeout=None)
        self.add_item(MembershipCheckButton(user_id))
        self.add_item(ConfigStatusButton(guild_id))

class Ticketing(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        bot.add_view(PurchasePanel())
        bot.add_view(PurchaseTierView())
        bot.add_view(EvidenceReviewView())
        bot.add_dynamic_items(MembershipCheckButton, ConfigStatusButton)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or not message.attachments:
            return
        ticket = await database.get_ticket(message.channel.id)
        if not ticket or ticket["approval_status"] != "pending" or ticket["ticket_type"] not in ("purchase", "renewal"):
            return
        images = [
            attachment for attachment in message.attachments
            if (attachment.content_type or "").startswith("image/")
            or attachment.filename.lower().endswith(IMAGE_EXTENSIONS)
        ]
        if not images:
            return
        await database.set_evidence(message.channel.id, message.id)
        cfg = await database.get_config(message.guild.id)
        embed = discord.Embed(
            title="Payment screenshot submitted",
            description=(f"User: {message.author} ({message.author.id})\n"
                         f"Email: {ticket.get('submitted_email') or 'Not supplied'}\n"
                         f"Plan: {(ticket.get('tenure') or 'Not selected').title()}"),
            color=discord.Color.gold()
        )
        embed.add_field(name="Evidence", value=f"[Open screenshot]({images[0].url})", inline=False)
        embed.set_image(url=images[0].url)
        staff_role = message.guild.get_role(cfg.get("staff_role_id")) if cfg and cfg.get("staff_role_id") else None
        await message.channel.send(
            content=staff_role.mention if staff_role else None,
            embed=embed, view=EvidenceReviewView(),
            allowed_mentions=discord.AllowedMentions(roles=True, everyone=False)
        )

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
