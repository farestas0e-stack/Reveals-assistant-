import hmac
import logging
import os

import discord
from aiohttp import web

import database

log = logging.getLogger("reveals-assistant.superprofile")


class SuperProfileWebhookServer:
    def __init__(self, bot):
        self.bot = bot
        self.runner = None

    async def start(self):
        secret = os.getenv("SUPERPROFILE_WEBHOOK_SECRET")
        if not secret:
            log.warning("SuperProfile webhook disabled: SUPERPROFILE_WEBHOOK_SECRET is not configured")
            return

        app = web.Application(client_max_size=64 * 1024)
        app.router.add_get("/health", self.health)
        app.router.add_post("/webhooks/superprofile", self.handle)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        port = int(os.getenv("PORT", "8080"))
        site = web.TCPSite(self.runner, "0.0.0.0", port)
        await site.start()
        log.info("SuperProfile webhook listening on port %s", port)

    async def close(self):
        if self.runner:
            await self.runner.cleanup()
            self.runner = None

    async def health(self, request):
        return web.json_response({"status": "ok", "service": "reveals-assistant"})

    def _authorized(self, request) -> bool:
        secret = os.getenv("SUPERPROFILE_WEBHOOK_SECRET", "")
        if not secret:
            return False
        authorization = request.headers.get("Authorization", "")
        supplied = request.headers.get("X-Webhook-Secret", "")
        return (
            hmac.compare_digest(authorization, f"Bearer {secret}")
            or hmac.compare_digest(supplied, secret)
        )

    async def _resolve_member(self, guild: discord.Guild, payload: dict):
        raw_id = payload.get("discord_user_id") or payload.get("discord_id")
        if raw_id is not None:
            value = str(raw_id).strip()
            if not value.isdigit():
                raise web.HTTPBadRequest(text="discord_user_id must be a numeric Discord user ID")
            try:
                return guild.get_member(int(value)) or await guild.fetch_member(int(value))
            except discord.NotFound:
                raise web.HTTPNotFound(text="Discord user is not a member of the configured Server A")
            except discord.HTTPException:
                log.exception("Could not fetch Discord user %s in guild %s", value, guild.id)
                raise web.HTTPServiceUnavailable(text="Discord member lookup failed; retry the webhook")

        username = str(payload.get("discord_username") or "").strip().lstrip("@")
        if not username:
            raise web.HTTPBadRequest(text="Provide discord_user_id or discord_username")
        try:
            candidates = await guild.query_members(query=username, limit=100)
        except discord.HTTPException:
            log.exception("Could not search for Discord username %s in guild %s", username, guild.id)
            raise web.HTTPServiceUnavailable(text="Discord username lookup failed; retry the webhook")
        exact = [
            member for member in candidates
            if member.name.casefold() == username.casefold()
            or member.display_name.casefold() == username.casefold()
            or (getattr(member, "global_name", None) or "").casefold() == username.casefold()
        ]
        if len(exact) == 0:
            raise web.HTTPNotFound(text="No exact Discord username match. Send the numeric Discord user ID instead.")
        if len(exact) > 1:
            raise web.HTTPConflict(text="Discord username is ambiguous. Send the numeric Discord user ID instead.")
        return exact[0]

    async def handle(self, request):
        if not self._authorized(request):
            raise web.HTTPUnauthorized(text="Invalid webhook secret")

        try:
            payload = await request.json()
        except (ValueError, web.HTTPException):
            raise web.HTTPBadRequest(text="Request body must be valid JSON")
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="JSON body must be an object")

        event_type = str(payload.get("event") or payload.get("event_type") or "").strip().lower()
        event_type = event_type.replace("-", "_").replace(" ", "_")
        if event_type not in {"purchase_successful", "subscription_expired"}:
            raise web.HTTPBadRequest(text="event must be purchase_successful or subscription_expired")

        event_id = str(payload.get("event_id") or payload.get("payment_id") or "").strip()
        if not event_id or len(event_id) > 200:
            raise web.HTTPBadRequest(text="A unique event_id or payment_id is required")

        raw_guild_id = payload.get("server_a_id") or payload.get("guild_id")
        if raw_guild_id is None or not str(raw_guild_id).isdigit():
            raise web.HTTPBadRequest(text="server_a_id must be the numeric ID of Server A")
        guild_id = int(raw_guild_id)
        cfg = await database.get_config(guild_id)
        if not cfg or cfg.get("server_a_id") != guild_id:
            raise web.HTTPNotFound(text="Server A is not configured in this bot")
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            raise web.HTTPServiceUnavailable(text="The bot is not connected to the configured Server A")

        role = guild.get_role(cfg.get("mentorship_role_id"))
        if role is None:
            raise web.HTTPConflict(text="The configured payment-verified role no longer exists")

        member = await self._resolve_member(guild, payload)
        claimed = await database.claim_provider_event("superprofile", event_id, event_type)
        if not claimed:
            return web.json_response({"status": "duplicate_ignored", "event_id": event_id})

        try:
            if event_type == "purchase_successful":
                if role not in member.roles:
                    mentorship = self.bot.get_cog("Mentorship")
                    if mentorship is None:
                        raise RuntimeError("Mentorship cog is not loaded")
                    mentorship._superprofile_assignments[(guild.id, member.id)] = {
                        "email": str(payload.get("email") or payload.get("customer_email") or "").strip() or None
                    }
                    try:
                        await member.add_roles(role, reason=f"Verified SuperProfile purchase: {event_id}")
                    except Exception:
                        mentorship._superprofile_assignments.pop((guild.id, member.id), None)
                        raise
                result = "role_assigned" if role not in member.roles else "already_has_role"
            else:
                if role in member.roles:
                    await member.remove_roles(role, reason=f"SuperProfile subscription expired: {event_id}")
                result = "role_removed" if role not in member.roles else "role_was_absent"

            await database.finish_provider_event("superprofile", event_id)
            log.info("Processed SuperProfile event %s for user %s: %s", event_id, member.id, result)
            return web.json_response({
                "status": "processed",
                "event_id": event_id,
                "event": event_type,
                "discord_user_id": member.id,
                "result": result
            })
        except Exception:
            await database.release_provider_event("superprofile", event_id)
            log.exception("SuperProfile event %s failed", event_id)
            raise web.HTTPServiceUnavailable(text="Event processing failed; retry the webhook")
