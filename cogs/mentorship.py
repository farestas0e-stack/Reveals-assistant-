import asyncio
import logging
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands, tasks

import database

log = logging.getLogger("reveals-assistant.mentorship")


async def _find_role_assigner(guild: discord.Guild, member_id: int, role_id: int):
    # Discord audit-log entries can arrive shortly after the member update event.
    await asyncio.sleep(1)
    try:
        async for entry in guild.audit_logs(limit=20, action=discord.AuditLogAction.member_role_update):
            if getattr(entry.target, "id", None) != member_id or not entry.user:
                continue
            if (discord.utils.utcnow() - entry.created_at).total_seconds() > 90:
                continue
            before_roles = {r.id for r in (getattr(entry.before, "roles", None) or [])}
            after_roles = {r.id for r in (getattr(entry.after, "roles", None) or [])}
            if role_id in after_roles and role_id not in before_roles:
                return entry.user
    except discord.Forbidden:
        log.error("Missing View Audit Log permission in guild %s; role assignment will not be trusted", guild.id)
    except discord.HTTPException:
        log.exception("Could not inspect role assignment audit log in guild %s", guild.id)
    return None


def _is_trusted_assigner(actor: discord.abc.User, cfg: dict, guild: discord.Guild) -> bool:
    if not isinstance(actor, discord.Member):
        actor = guild.get_member(actor.id)
    if actor is None:
        return False
    trusted_ids = {
        cfg.get("trusted_provider_manager_role_id"),
        cfg.get("sales_staff_role_id"),
    }
    trusted_ids.discard(None)
    has_configured_trusted_role = any(role.id in trusted_ids for role in actor.roles)
    # Any moderator who can manage roles in Discord may grant the mentorship role.
    return has_configured_trusted_role or actor.guild_permissions.manage_roles or actor.guild_permissions.administrator


async def _send_log(guild: discord.Guild, cfg: dict, title: str, member_id: int,
                    email: str | None, detail: str, color: discord.Color):
    if guild is None:
        return
    channel_ids = [cfg.get("sales_channel_id")]
    lowered = title.casefold()
    if any(word in lowered for word in ("assigned", "approved", "access granted")):
        channel_ids.append(cfg.get("role_assigned_channel_id"))
    if any(word in lowered for word in ("revoked", "removed", "kicked")):
        channel_ids.append(cfg.get("role_revoked_channel_id"))
    embed = discord.Embed(title=title, color=color, timestamp=discord.utils.utcnow())
    embed.add_field(name="Discord user", value=f"<@{member_id}> ({member_id})", inline=False)
    embed.add_field(name="Payment email", value=email or "Not recorded", inline=True)
    embed.add_field(name="Purchase tenure", value="Provider-confirmed; role-based access", inline=True)
    embed.add_field(name="Details", value=detail[:1024], inline=False)
    for channel_id in dict.fromkeys(channel_ids):
        channel = guild.get_channel(channel_id) if channel_id else None
        if not isinstance(channel, discord.TextChannel):
            continue
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            log.exception("Could not send membership event log to channel %s", channel_id)


class AttributionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def _choose(self, interaction: discord.Interaction, source: str):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.followup.send("Use this in your private purchase ticket.", ephemeral=True)
        ticket = await database.get_ticket(interaction.channel_id)
        if not ticket or ticket["user_id"] != interaction.user.id:
            return await interaction.followup.send("Only the ticket owner can submit this answer.", ephemeral=True)
        cfg = await database.get_config(ticket["guild_id"])
        if not cfg or not cfg.get("server_b_id"):
            return await interaction.followup.send("Server B is not configured. Contact staff.", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        await database.save_attribution(ticket["guild_id"], interaction.user.id, interaction.channel_id, source)
        community = interaction.client.get_guild(cfg["server_b_id"])
        if community is None:
            return await interaction.followup.send("Server B is unavailable. Staff have been notified.", ephemeral=True)
        invite_channel = next((ch for ch in community.text_channels
            if community.me and ch.permissions_for(community.me).create_instant_invite), None)
        if invite_channel is None:
            return await interaction.followup.send("The bot cannot create an invitation right now. Contact staff.", ephemeral=True)
        try:
            invite = None
            existing_records = await database.active_invites_for_user(ticket["guild_id"], interaction.user.id)
            if existing_records:
                available_invites = await community.invites()
                invite = next((item for item in available_invites
                               if item.code == existing_records[0]["invite_code"]), None)
            if invite is None:
                invite = await invite_channel.create_invite(
                    max_age=86400, max_uses=1, unique=True,
                    reason=f"Approved mentorship access for Discord user {interaction.user.id}"
                )
                expires_at = (discord.utils.utcnow() + timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
                await database.add_community_invite(
                    invite.code, ticket["guild_id"], community.id, interaction.user.id,
                    interaction.channel_id, expires_at, ticket.get("submitted_email")
                )
        except (discord.HTTPException, ValueError):
            log.exception("Could not create one-use community invite for %s", interaction.user.id)
            return await interaction.followup.send("Invitation creation failed. Staff have been notified.", ephemeral=True)

        message = (
            f"Your mentorship access is approved. Join Server B within 24 hours using this "
            f"single-use invitation: {invite.url}"
        )
        delivered_by = "private ticket fallback"
        try:
            await interaction.user.send(message)
            delivered_by = "direct message"
        except discord.HTTPException:
            try:
                await interaction.channel.send(f"{interaction.user.mention} {message}")
            except discord.HTTPException:
                log.exception("Could not deliver invite to user %s", interaction.user.id)
                return await interaction.followup.send(
                    "The invite was created, but neither DM nor ticket delivery worked. Contact staff before requesting another invite.",
                    ephemeral=True
                )
        await database.record_membership_event(
            ticket["guild_id"], community.id, interaction.user.id,
            "invite_created", interaction.client.user.id if interaction.client.user else None,
            f"Attribution={source}; delivery={delivered_by}; invite expires in 24 hours; one use"
        )
        await interaction.followup.send(
            f"Recorded: **{source.replace('_', ' ').title()}**. Your invitation was sent by {delivered_by}.",
            ephemeral=True
        )
        await _send_log(
            interaction.guild, cfg, "Mentorship approved — invitation issued",
            interaction.user.id, ticket.get("submitted_email"),
            f"Attribution: {source.replace('_', ' ').title()}. Invitation expires in 24 hours and allows one use.",
            discord.Color.green()
        )

    @discord.ui.button(label="YouTube", style=discord.ButtonStyle.primary, custom_id="reveals:attribution_youtube")
    async def youtube(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._choose(interaction, "youtube")

    @discord.ui.button(label="Instagram", style=discord.ButtonStyle.primary, custom_id="reveals:attribution_instagram")
    async def instagram(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._choose(interaction, "instagram")

    @discord.ui.button(label="Sales team", style=discord.ButtonStyle.success, custom_id="reveals:attribution_sales")
    async def sales(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._choose(interaction, "sales_team")


class Mentorship(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._offboarding: set[tuple[int, int]] = set()
        self._rejected_assignments: set[tuple[int, int]] = set()
        self._superprofile_assignments: dict[tuple[int, int], dict] = {}
        self._invite_cache: dict[int, dict[str, int]] = {}
        bot.add_view(AttributionView())
        self.access_reconciliation.start()

    async def cog_load(self):
        await self._refresh_invite_cache()

    @commands.Cog.listener()
    async def on_ready(self):
        await self._refresh_invite_cache()

    def cog_unload(self):
        self.access_reconciliation.cancel()

    async def _refresh_invite_cache(self):
        for guild in self.bot.guilds:
            cfg = await database.get_config_by_server_b_id(guild.id)
            if not cfg or guild.id != cfg.get("server_b_id"):
                continue
            try:
                invites = await guild.invites()
                self._invite_cache[guild.id] = {invite.code: invite.uses or 0 for invite in invites}
            except discord.HTTPException:
                log.warning("Could not cache invites for Server B %s", guild.id)

    async def _kick_from_community(self, cfg: dict, user_id: int, reason: str):
        community = self.bot.get_guild(cfg.get("server_b_id"))
        if community is None:
            log.error("Server B %s is unavailable; cannot offboard %s", cfg.get("server_b_id"), user_id)
            return
        try:
            member = community.get_member(user_id) or await community.fetch_member(user_id)
        except discord.NotFound:
            return
        except discord.HTTPException:
            log.exception("Could not fetch Server B member %s", user_id)
            return
        if member:
            try:
                await member.kick(reason=reason)
                await database.record_membership_event(
                    cfg.get("server_a_id"), community.id, user_id, "kicked_from_server_b",
                    self.bot.user.id if self.bot.user else None, reason
                )
                await _send_log(
                    self.bot.get_guild(cfg.get("server_a_id")), cfg,
                    "Server B membership removed", user_id, None, reason, discord.Color.red()
                )
            except discord.HTTPException:
                log.exception("Could not kick %s from Server B", user_id)

    async def _offboard(self, source: discord.Guild, user_id: int, cfg: dict,
                        reason: str, member: discord.Member | None = None):
        key = (source.id, user_id)
        if key in self._offboarding:
            return
        self._offboarding.add(key)
        try:
            sub = await database.get_subscription(user_id, source.id)
            await self._kick_from_community(cfg, user_id, reason)
            renewal_url = cfg.get("renewal_url")
            message = (
                f"Your mentorship access has ended. Renew your access here: {renewal_url}"
                if renewal_url else
                "Your mentorship access has ended. Please contact the team to renew."
            )
            dm_sent = False
            try:
                user = await self.bot.fetch_user(user_id)
                await user.send(message)
                dm_sent = True
            except discord.HTTPException:
                log.info("Renewal DM could not be delivered to %s", user_id)
            if not dm_sent:
                current_member = member or source.get_member(user_id)
                if current_member:
                    try:
                        from .ticketing import create_private_ticket
                        await create_private_ticket(source, current_member, cfg, "renewal", (sub or {}).get("email"))
                    except (discord.HTTPException, ValueError):
                        log.exception("Could not create renewal ticket for %s", user_id)
            await database.deactivate_subscription(user_id, source.id)
            role = source.get_role(cfg.get("mentorship_role_id"))
            if role:
                revoked_channel = source.get_channel(cfg.get("role_revoked_channel_id"))
                if isinstance(revoked_channel, discord.TextChannel):
                    embed = discord.Embed(title="Mentorship role revoked", color=discord.Color.red())
                    embed.add_field(name="Discord user", value=f"<@{user_id}> ({user_id})", inline=False)
                    embed.add_field(name="Payment email", value=(sub or {}).get("email") or "Not recorded", inline=True)
                    embed.add_field(name="Reason", value=reason, inline=False)
                    await revoked_channel.send(embed=embed)
        finally:
            self._offboarding.discard(key)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        cfg = await database.get_config(after.guild.id)
        if not cfg or after.guild.id != cfg.get("server_a_id"):
            return
        role = after.guild.get_role(cfg.get("mentorship_role_id"))
        if role is None or ((role in before.roles) == (role in after.roles)):
            return
        sub = await database.get_subscription(after.id, after.guild.id)
        if role in after.roles:
            context = self._superprofile_assignments.pop((after.guild.id, after.id), None)
            actor = None
            if context:
                actor_label = "Verified SuperProfile webhook"
                sub = {**(sub or {}), "email": context.get("email") or (sub or {}).get("email")}
                trusted = True
            else:
                actor = await _find_role_assigner(after.guild, after.id, role.id)
                trusted = _is_trusted_assigner(actor, cfg, after.guild) if actor else False
                actor_label = str(actor) if actor else "Unverified actor"
            if not trusted:
                # Never undo a human role change. If the audit-log actor cannot be
                # verified, leave the role untouched and do not trigger approval.
                log.warning("Mentorship role assignment left untouched; assigner lacks verified Manage Roles permission: guild=%s user=%s actor=%s",
                            after.guild.id, after.id, getattr(actor, "id", None))
                await database.record_membership_event(
                    after.guild.id, cfg.get("server_b_id"), after.id,
                    "role_assignment_left_untouched", getattr(actor, "id", None),
                    "Bot did not remove the role; approval automation skipped because the assigner could not be verified"
                )
                return
            await database.record_membership_event(
                after.guild.id, cfg.get("server_b_id"), after.id, "payment_role_assigned",
                getattr(actor, "id", None), actor_label
            )
            from .ticketing import create_private_ticket
            ticket_id = await database.find_open_ticket(after.guild.id, after.id, "purchase")
            if ticket_id is None:
                ticket_id = await database.find_open_ticket(after.guild.id, after.id, "renewal")
            ticket = after.guild.get_channel(ticket_id) if ticket_id else None
            if not isinstance(ticket, discord.TextChannel):
                try:
                    ticket = await create_private_ticket(after.guild, after, cfg, "purchase", (sub or {}).get("email"))
                except (discord.HTTPException, ValueError):
                    log.exception("Could not create post-approval ticket for %s", after.id)
                    return
            await database.mark_ticket_access_granted(ticket.id, (sub or {}).get("email"))
            ticket_record = await database.get_ticket(ticket.id)
            buyer_email = (sub or {}).get("email") or (ticket_record or {}).get("submitted_email")

            # The configured mentorship role is the purchase-verification signal.
            # Issue the Server B invite immediately; no attribution click or extra
            # staff action is required after the role is assigned.
            community = self.bot.get_guild(cfg.get("server_b_id"))
            invite = None
            if community is not None:
                invite_channel = next((ch for ch in community.text_channels
                    if community.me and ch.permissions_for(community.me).create_instant_invite), None)
                if invite_channel is not None:
                    try:
                        existing_records = await database.active_invites_for_user(after.guild.id, after.id)
                        if existing_records:
                            available_invites = await community.invites()
                            invite = next((item for item in available_invites
                                if item.code == existing_records[0]["invite_code"]), None)
                        if invite is None:
                            invite = await invite_channel.create_invite(
                                max_age=86400, max_uses=1, unique=True,
                                reason=f"Verified mentorship purchase for Discord user {after.id}"
                            )
                            expires_at = (discord.utils.utcnow() + timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
                            await database.add_community_invite(
                                invite.code, after.guild.id, community.id, after.id,
                                ticket.id, expires_at, buyer_email
                            )
                    except (discord.HTTPException, ValueError):
                        log.exception("Could not create Server B invite immediately after role verification for %s", after.id)
                else:
                    log.error("No Server B channel allows invite creation; verified buyer=%s", after.id)
            else:
                log.error("Server B is unavailable; cannot invite verified buyer=%s", after.id)

            invite_delivery = "not delivered"
            if invite is not None:
                invite_message = (
                    f"Your purchase is verified. Join Server B within 24 hours using this "
                    f"single-use invitation: {invite.url}"
                )
                try:
                    await after.send(invite_message)
                    invite_delivery = "DM"
                except discord.HTTPException:
                    try:
                        await ticket.send(f"{after.mention} {invite_message}")
                        invite_delivery = "private ticket"
                    except discord.HTTPException:
                        log.exception("Could not deliver Server B invite to verified buyer %s", after.id)

            embed = discord.Embed(
                title="Purchase verified",
                description=(
                    f"{after.mention}, assigning the configured mentorship role counts as purchase verification. "
                    + (f"Your 24-hour, single-use Server B invitation was sent by {invite_delivery}."
                       if invite is not None else
                       "Your purchase is verified, but the invitation could not be created. Staff must check Server B invite permissions/configuration.")
                ),
                color=discord.Color.green()
            )
            embed.add_field(name="Verified by", value=actor_label, inline=False)
            await ticket.send(embed=embed)
            await database.record_membership_event(
                after.guild.id, cfg.get("server_b_id"), after.id, "purchase_verified_invite_issued",
                getattr(actor, "id", None), f"Verified by: {actor_label}; invite delivery: {invite_delivery}"
            )
            await _send_log(after.guild, cfg, "Approved payout role assigned", after.id,
                            buyer_email, f"Verified by: {actor_label}; Server B invite delivery: {invite_delivery}",
                            discord.Color.green())
        else:
            if (after.guild.id, after.id) in self._rejected_assignments:
                self._rejected_assignments.discard((after.guild.id, after.id))
                return
            await self._offboard(after.guild, after.id, cfg,
                                 "Mentorship role removed in Server A", member=after)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        cfg = await database.get_config_by_server_b_id(member.guild.id)
        if not cfg or member.guild.id != cfg.get("server_b_id"):
            return
        try:
            current_invites = await member.guild.invites()
        except discord.HTTPException:
            log.exception("Could not inspect Server B invites after join")
            return
        previous = self._invite_cache.get(member.guild.id, {})
        used = [invite for invite in current_invites
                if (invite.uses or 0) > previous.get(invite.code, 0)]
        self._invite_cache[member.guild.id] = {invite.code: invite.uses or 0 for invite in current_invites}
        if len(used) != 1:
            log.warning("Could not uniquely attribute Server B join for user %s", member.id)
            return
        record = await database.get_pending_invite_by_code(used[0].code)
        if not record or record["user_id"] != member.id or record["guild_b_id"] != member.guild.id:
            log.warning("Server B join did not match the intended user/invite: user=%s", member.id)
            return
        if not await database.consume_community_invite(used[0].code, member.id):
            return
        role = member.guild.get_role(cfg.get("community_mentorship_role_id"))
        if role is None:
            log.error("Server B mentorship role is not configured; cannot grant role to %s", member.id)
            return
        try:
            await member.add_roles(role, reason="Verified one-use mentorship invitation")
        except discord.HTTPException:
            log.exception("Could not assign Server B mentorship role to %s", member.id)
            return
        await database.record_membership_event(
            cfg.get("server_a_id"), member.guild.id, member.id, "server_b_access_granted",
            self.bot.user.id if self.bot.user else None, "One-use 24-hour invite matched"
        )
        ticket_id = record.get("ticket_channel_id")
        ticket = self.bot.get_channel(ticket_id) if ticket_id else None
        if isinstance(ticket, discord.TextChannel):
            await database.close_ticket(ticket.id)
            try:
                await ticket.delete(reason="Buyer joined Server B and received mentorship role")
            except discord.HTTPException:
                log.exception("Could not delete completed purchase ticket %s", ticket.id)
        source = self.bot.get_guild(cfg.get("server_a_id"))
        if source:
            await _send_log(source, cfg, "Server B access granted", member.id, record.get("email"),
                            "Buyer joined using their assigned one-use invitation; Server B role assigned.",
                            discord.Color.green())

    @tasks.loop(minutes=20)
    async def access_reconciliation(self):
        await self.bot.wait_until_ready()
        for source in self.bot.guilds:
            cfg = await database.get_config(source.id)
            if not cfg or source.id != cfg.get("server_a_id"):
                continue
            community = self.bot.get_guild(cfg.get("server_b_id"))
            role = source.get_role(cfg.get("mentorship_role_id"))
            if community is None or role is None:
                continue
            for community_member in list(community.members):
                try:
                    source_member = source.get_member(community_member.id) or await source.fetch_member(community_member.id)
                except discord.NotFound:
                    await self._kick_from_community(cfg, community_member.id,
                                                    "User is no longer a member of Server A")
                    continue
                except discord.HTTPException:
                    log.warning("Could not reconcile Server A membership for %s", community_member.id)
                    continue
                if role not in source_member.roles:
                    await self._kick_from_community(
                        cfg, community_member.id,
                        "Required mentorship role is missing in Server A"
                    )

    @access_reconciliation.before_loop
    async def before_access_reconciliation(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Mentorship(bot))
