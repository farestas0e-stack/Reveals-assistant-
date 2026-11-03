# Reveals Assistant

Python 3.10+ Discord bot for a three-server mentorship workflow.

## Features
- Server A mentorship-role assignment creates a subscription record and posts a role-assignment alert.
- Server B access invites are single-use and expire after 24 hours.
- Removing the mentorship role in Server A revokes the subscription and attempts to kick the member from Server B.
- Expired subscriptions are checked every five minutes. The bot attempts the Server B kick, removes the Server A role, then sends a renewal DM. If DMs fail, it opens a private renewal ticket.
- Persistent mentorship purchase panel with an email modal first, private purchase tickets, staff payment verification, invite delivery only after approval, and ticket closing.
- Staff-approved verified purchase creates and delivers a one-use, 24-hour Server B invite. Role assignment by itself never sends an invite.
- Category overflow creates additional ticket categories.
- Category-wide /broadcast.
- Separate mentorship role-assigned and role-revoked alerts in Server A; ban/kick and message-delete forwarding to Server C.

## Important payment limitation
There is **no verified Superprofile webhook integration in this repository**. A role assignment is only an alert and must not be treated as proof of payment. For now, staff must independently verify the payment in Superprofile/payment dashboard and then run /approve_purchase in the student's ticket. Do not run that command until payment is confirmed. A real automatic integration requires Superprofile's official webhook documentation, event/signature format, and a webhook secret; none of those credentials should be committed to GitHub.

## 1. Create the Discord application
1. Create a bot in the Discord Developer Portal and copy its token.
2. Under Bot > Privileged Gateway Intents, enable **Server Members Intent** and **Message Content Intent**.
3. Invite the bot to Servers A and B, and Server C if using forwarded logs.
4. Grant Administrator temporarily for initial setup, or grant the least permissions needed:
   - Server A: View Channels, Send Messages, Embed Links, Manage Channels, Manage Roles, View Audit Log.
   - Server B: View Channels, Create Instant Invite, Kick Members.
   - Server C: View Channels, Send Messages, Embed Links.
5. Put the bot's highest role above the mentorship role and above members it must kick.

## 2. Configure hosting
Set environment variables in the host dashboard:
- DISCORD_TOKEN = bot token
- LOG_LEVEL = INFO (optional)

Run command:
`python main.py`

Use persistent storage for `bot.sqlite3`. On Railway, attach a persistent volume and set its mount path to `/app/data`, then set `DB_PATH=/app/data/bot.sqlite3` if you choose that path. The default database path is the project directory; it will be lost on hosts with ephemeral filesystems.

## 3. Configure the bot in Discord
Run `/setup` inside Server A. Select:
- Server B ID (copy with Developer Mode)
- Mentorship role in Server A
- Sales alert channel in Server A
- Separate mentorship role-assigned and role-revoked alert channels in Server A
- Purchase ticket category in Server A
- Renewal ticket category in Server A
- Renewal/payment URL
- Subscription duration in days
- Optional Server C ID and its log-channel ID

The bot must already be in Server B before setup.

Then:
1. Run `/mentorship_panel` in Server A and select the public panel channel.
2. Have a test user click Purchase Mentorship and submit their Whop/payment email in the modal.
3. The bot creates a private ticket and records the submitted email. Staff checks the actual payment receipt outside Discord (no automatic Whop/Superprofile sync is configured).
4. In that user's ticket, staff runs `/approve_purchase email:...`.
5. Test invite use, expiry, role revocation, subscription expiry, closed DMs, and Server C logs before going live.

## Commands
- `/setup` — configure the Server A workflow (Administrator).
- `/mentorship_panel` — post the purchase panel (Administrator).
- `/approve_purchase email:<email>` — approve a manually verified purchase (Manage Channels).
- `/close_ticket` — close a registered ticket (Manage Channels).
- `/broadcast category:<category> message:<text>` — send to accessible text channels in a category (Administrator).

## Operational notes
- Keep the bot token private. If it is exposed, regenerate it immediately.
- Never commit `.env`, SQLite database files, or payment secrets.
- SQLite is suitable for a single bot process on one persistent disk. Do not run multiple bot replicas against the same SQLite file.
- Message-delete forwarding only has message content when Discord.py had the message cached. Discord does not provide deleted message content in every case.
- The bot cannot verify a payment by email alone, and no Whop/Superprofile sync is configured. Staff must independently confirm the receipt; only ticket approval can create and deliver a Server B invite. Manually adding the mentorship role never sends an invite.
- Test with a private test server and test account before using paid customers.
