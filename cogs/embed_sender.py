import re
from urllib.parse import urlparse

import discord
from discord import app_commands
from discord.ext import commands


def valid_http_url(value: str | None) -> bool:
    if not value:
        return True
    parsed = urlparse(value.strip())
    return parsed.scheme in ("https", "http") and bool(parsed.netloc)


def parse_fields(raw: str | None):
    if not raw:
        return []
    fields = []
    for line_number, line in enumerate(raw.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split("|", 2)]
        if len(parts) < 2 or not parts[0] or not parts[1]:
            raise ValueError(
                f"Field line {line_number} must use: Name | Value | inline (optional)."
            )
        inline = False
        if len(parts) == 3:
            flag = parts[2].lower()
            if flag not in ("true", "false", "yes", "no", "inline", "block"):
                raise ValueError(
                    f"Field line {line_number}: inline must be true/false."
                )
            inline = flag in ("true", "yes", "inline")
        fields.append((parts[0], parts[1], inline))
    if len(fields) > 25:
        raise ValueError("Discord embeds support a maximum of 25 fields.")
    return fields


class EmbedSender(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="embed_send",
        description="Create and send a custom embed to a channel."
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        channel="Where the embed should be posted",
        description="Main embed message (up to 4,000 characters)",
        title="Optional embed title",
        color="Hex color, e.g. #5865F2 or #FF9900",
        fields="One per line: Name | Value | true/false (inline optional)",
        footer="Optional footer text",
        author="Optional author heading",
        image_url="Optional large image URL",
        thumbnail_url="Optional small thumbnail URL"
    )
    async def embed_send(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        description: str,
        title: str | None = None,
        color: str = "#5865F2",
        fields: str | None = None,
        footer: str | None = None,
        author: str | None = None,
        image_url: str | None = None,
        thumbnail_url: str | None = None,
    ):
        if not description.strip():
            return await interaction.response.send_message(
                "Embed description cannot be empty.", ephemeral=True
            )
        if title and len(title) > 256:
            return await interaction.response.send_message(
                "Title must be 256 characters or fewer.", ephemeral=True
            )
        if len(description) > 4000:
            return await interaction.response.send_message(
                "Description must be 4,000 characters or fewer.", ephemeral=True
            )
        if footer and len(footer) > 2048:
            return await interaction.response.send_message(
                "Footer must be 2,048 characters or fewer.", ephemeral=True
            )
        if author and len(author) > 256:
            return await interaction.response.send_message(
                "Author must be 256 characters or fewer.", ephemeral=True
            )
        if not valid_http_url(image_url) or not valid_http_url(thumbnail_url):
            return await interaction.response.send_message(
                "Image and thumbnail must be valid HTTP or HTTPS URLs.", ephemeral=True
            )
        try:
            color_value = int(color.strip().removeprefix("#"), 16)
            if not 0 <= color_value <= 0xFFFFFF:
                raise ValueError
            parsed_fields = parse_fields(fields)
        except ValueError as exc:
            message = str(exc) or "Color must be a hex value such as #5865F2."
            return await interaction.response.send_message(message, ephemeral=True)

        embed = discord.Embed(
            title=title or None,
            description=description,
            color=discord.Color(color_value),
        )
        for name, value, inline in parsed_fields:
            if len(name) > 256 or len(value) > 1024:
                return await interaction.response.send_message(
                    "Each field name must be at most 256 characters and each value at most 1,024.",
                    ephemeral=True,
                )
            embed.add_field(name=name, value=value, inline=inline)
        if footer:
            embed.set_footer(text=footer)
        if author:
            embed.set_author(name=author)
        if image_url:
            embed.set_image(url=image_url.strip())
        if thumbnail_url:
            embed.set_thumbnail(url=thumbnail_url.strip())

        bot_member = interaction.guild.me if interaction.guild else None
        permissions = channel.permissions_for(bot_member) if bot_member else None
        if not permissions or not permissions.send_messages or not permissions.embed_links:
            return await interaction.response.send_message(
                "I need Send Messages and Embed Links permissions in that channel.",
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            return await interaction.followup.send(
                "Discord denied permission to send the embed in that channel.",
                ephemeral=True,
            )
        except discord.HTTPException as exc:
            return await interaction.followup.send(
                f"Discord could not send the embed: {exc}", ephemeral=True
            )
        await interaction.followup.send(
            f"Custom embed sent to {channel.mention}.", ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(EmbedSender(bot))
