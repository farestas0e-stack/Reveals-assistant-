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
- The role-assigned log contains Administrator-only approval buttons for either 30 or 90 days. After an Administrator verifies the screenshot in the sales channel, they choose the duration in that log. Approval stores the selected term and sends a one-use Server B invite.
- If the member's DMs are closed, the invite is posted in their private ticket. If both delivery paths fail, the approval interaction gives the Administrator the invite URL for manual delivery.
- Purchase/renewal tickets have a Close ticket button. Ticket categories automatically roll over before reaching Discord's category channel limit.
- Role assignment and revocation logs are sent to separate channels. A role-assigned event is logged once, only in the role-assigned channel, with the member, role, assigning user (when Discord audit logs expose it), and approval duration. The role-assigned log offers 30-day and 90-day purchase verification/approval buttons. Approved logs retain membership-status and Send Server B invite controls.
- The bot checks active memberships every 20 minutes. If the configured role disappears or the stored membership expires, it attempts to kick the member from Server B, send renewal instructions by DM, and create a private renewal ticket if DMs fail.
- /broadcast sends to text channels in a category. Its mention_users option controls whether user mentions are allowed; role and @everyone mentions remain disabled.
- Optional Server C forwarding supports member bans, detected kicks and cached message deletions.

## Payment provider integration: important limitation

There is no verified SuperProfile or Whop API/webhook integration in this repository. The implemented safe workflow is manual evidence review: the customer submits their payment email and screenshot, and an Administrator verifies the transaction in the provider dashboard before pressing Approve Purchase.

SuperProfile or an authorized staff workflow may assign the mentorship role automatically. The bot does not assign it as part of purchase approval. Role assignment alone does not grant Server B access: an Administrator must verify the screenshot and approve 30 or 90 days from the role-assigned log. To automate provider verification, the provider must supply official webhook documentation, event types, signature verification rules and a webhook secret. These details must not be guessed or committed to GitHub.

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

Place the bot's highest role above the mentorship role. Only trusted Administrators should have permission to approve payment screenshots. Keep the bot's permissions and staff roles restricted.

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
5. Confirm the evidence embed and review buttons appear.
6. As an Administrator, reject a test ticket and confirm no role or invite is issued.
7. For a separate test purchase, verify payment in the provider dashboard and click Approve Purchase.
8. Confirm the mentorship role is assigned, a subscription is stored and the one-use Server B invite is delivered.
9. Confirm the invite can only be used once and expires after 24 hours.
10. Remove the mentorship role and confirm the Server B kick, renewal DM and fallback ticket behavior.
11. Test with DMs closed and test the 20-minute expiry check.

## Commands

| Command | Purpose |
|---|---|
| /setup | Configure Server A/B/C, role, categories, channels and checkout links (Administrator) |
| /setup_status | Show saved setup status (Administrator) |
| /mentorship_panel | Post the purchase panel (Administrator) |
| /membership_status | Inspect active or inactive membership data (Manage Roles) |
| /close_ticket | Close and delete the current registered ticket (Manage Channels) |
| /broadcast | Broadcast to accessible text channels (Administrator) |

Ticket owners can also use the Close ticket button. Payment approval is handled by the 30-day and 90-day buttons on the role-assigned log.

## Practical limitations and operations

- Discord role changes and ticket actions require the bot to be online. The scheduled membership verification runs every 20 minutes while the process is running.
- The bot cannot confirm whether an external payment screenshot is genuine. A human Administrator must independently verify the transaction before approval.
- SuperProfile and Whop customer records are not currently synchronized automatically. The submitted email is stored for staff review.
- If a customer leaves Server A before a renewal ticket can be created, the bot posts a staff alert in the sales channel instead.
- Message-delete forwarding only includes content cached by discord.py; Discord does not provide deleted message content in every case.
- Never commit .env, bot tokens, webhook secrets or the SQLite database. Rotate the Discord token immediately if it is exposed.
