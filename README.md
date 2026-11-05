# Reveals Assistant

A Python 3.10+ Discord bot for a multi-server mentorship membership workflow. It uses discord.py 2.x, asyncio and SQLite (aiosqlite).

## Implemented workflow

- Server A is the sales, purchase-ticket and payment-verification server.
- Server B is the gated community. A successful staff approval creates a one-use invite that expires after 24 hours.
- Optional Server C receives moderation events from Server A.
- /setup stores all server, role, channel, category and checkout settings in SQLite. No server/channel/role IDs are hardcoded.
- /mentorship_panel posts an embed with a Purchase Mentorship button. The modal collects the buyer's Whop/payment email before creating a private ticket.
- The ticket provides one membership checkout link. The buyer uploads a payment screenshot; the sales channel receives only the screenshot attachment.
- Role assignment is handled automatically by the payment provider or authorized staff. The bot never assigns the mentorship role during purchase approval. It logs the assigned role and identifies the assigning user from Discord audit logs when available.
- Assigning the configured payment-verified role is the payment confirmation signal. The bot automatically creates a one-use Server B invite and sends it independently in both the member DM and their private ticket. There is no manual approval step and no membership expiry calculation.
- If the member's DMs are closed, the invite is posted in their private ticket. If both delivery paths fail, the approval interaction gives the Administrator the invite URL for manual delivery.
- Purchase/renewal tickets have a Close ticket button. Ticket categories automatically roll over before reaching Discord's category channel limit.
- Role assignment and revocation logs are sent to separate channels. A role-assigned event is logged once, with the member, role, assigning user (when Discord audit logs expose it), and role-based/no-expiry access status. There are no manual approval buttons.
- Removing the configured membership role triggers offboarding from Server B and sends renewal instructions. The bot does not calculate membership expiry.
- /broadcast sends to text channels in a category. Its mention_users option controls whether user mentions are allowed; role and @everyone mentions remain disabled.
- Optional Server C forwarding supports member bans, detected kicks and cached message deletions.

## Payment provider integration: important limitation

There is no verified SuperProfile or Whop API/webhook integration in this repository. SuperProfile must assign the configured Discord membership role when payment succeeds; that role assignment is treated as the verification event.

The bot watches for that role being added. It then grants Server B access automatically and sends the same one-use invite in both the member DM and private ticket. Role removal triggers offboarding. No duration or expiry calculation is used. If SuperProfile cannot assign Discord roles directly, an official provider integration or authorized role-sync workflow is still required; do not invent webhook endpoints or secrets.

## 1. Discord application and permissions

Enable these privileged intents in the Discord Developer Portal:
- Server Members Intent
- Message Content Intent

Invite the bot to Server A and Server B (and Server C if used). The bot needs:

**Server A**
- View Channels, Send Messages, Embed Links, Read Message History
- View Audit Log (so the bot can identify who assigned the mentorship role)
- Manage Channels, Manage Roles
- Access to the configured ticket categories and log channels

**Server B**
- View Channels, Create Instant Invite, Kick Members

**Server C (optional)**
- View Channels, Send Messages, Embed Links

Place the bot's highest role above the mentorship role. Keep the bot's permissions and staff roles restricted.

## 2. Hosting and persistent database

Install dependencies with: python -m pip install -r requirements.txt

Start the bot with: python main.py

Environment variables:
- DISCORD_TOKEN: bot token (secret)
- DB_PATH: SQLite database path (recommended on Railway: /app/data/bot.sqlite3)
- LOG_LEVEL: optional, defaults to INFO

On Railway, attach a persistent volume mounted at /app/data and set DB_PATH=/app/data/bot.sqlite3. Do not delete the volume when redeploying. Run only one bot replica against this SQLite database.

## 3. First-time setup in Discord

Run /setup in Server A as an Administrator. Supply:
1. Server B ID
2. Mentorship/payment-verified role ID in Server A
3. Sales log channel ID in Server A
4. Role-assigned log channel ID in Server A
5. Role-revoked log channel ID in Server A
6. Purchase ticket category ID in Server A
7. Renewal ticket category ID in Server A
8. Single membership / renewal checkout URL
9. Optional staff role ID
10. Optional Server C ID
11. Optional Server C log channel ID

Copy IDs with Discord Developer Mode enabled. The bot validates the configured channels, role, Server B membership and core permissions. Then run /setup_status to inspect saved configuration.

Next, run /mentorship_panel and select the public purchase-panel channel.

## 4. Test purchase procedure

Use a test account and test payment method first:
1. Click Purchase Mentorship and submit the payment email.
2. Confirm a private ticket is created and only the buyer/staff can view it.
3. Click Get membership link and confirm the single checkout link is shown.
4. Upload a test receipt image.
5. Confirm the screenshot embed is forwarded to the sales log.
6. Assign the configured membership role to the test account.
7. Confirm the role-assigned log appears and the same one-use invite is sent in both DM and private ticket.
8. Confirm the invite can only be used once and expires after 24 hours.
9. Remove the membership role and confirm the Server B kick and renewal message.

## Commands

| Command | Purpose |
|---|---|
| /setup | Configure Server A/B/C, role, categories, channels and checkout links (Administrator) |
| /setup_status | Show saved setup status (Administrator) |
| /mentorship_panel | Post the purchase panel (Administrator) |
| /membership_status | Inspect active or inactive membership data (Manage Roles) |
| /close_ticket | Close and delete the current registered ticket (Manage Channels) |
| /broadcast | Broadcast to accessible text channels (Administrator) |

Ticket owners can also use the Close ticket button. The configured membership role assignment automatically verifies payment and grants Server B access.

## Practical limitations and operations

- Discord role changes and ticket actions require the bot to be online.
- SuperProfile and Whop customer records are not synchronized automatically. SuperProfile must assign the configured role; the bot reacts to that Discord role event.
- If a customer leaves Server A before a renewal ticket can be created, the bot posts a staff alert in the sales channel instead.
- Message-delete forwarding only includes content cached by discord.py; Discord does not provide deleted message content in every case.
- Never commit .env, bot tokens, webhook secrets or the SQLite database. Rotate the Discord token immediately if it is exposed.
