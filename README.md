# Reveals Assistant

A Python 3.10+ Discord bot for a multi-server mentorship membership workflow. It uses discord.py 2.x, asyncio and SQLite (aiosqlite).

## Implemented workflow

- Server A is the sales, purchase-ticket and payment-verification server.
- Server B is the gated community. The existing SuperProfile webhook remains supported, and authorized Trusted Provider Managers or Sales Staff can confirm provider-approved payouts by assigning the configured mentorship role in Server A.
- /setup stores all server, role, channel, category and checkout settings in SQLite. No server/channel/role IDs are hardcoded.
- /mentorship_panel posts an embed with a Purchase Mentorship button. The modal collects the buyer's Whop/payment email before creating a private ticket.
- The ticket provides one membership checkout link. The buyer uploads a payment screenshot; the sales channel receives only the screenshot attachment.
- SuperProfile purchase and subscription-expired events can be relayed through Pabbly to the bot's authenticated webhook. The bot assigns or removes the configured role and records SuperProfile as the source in the role log.
- Payment confirmation is a trusted role assignment: the bot checks Discord audit logs and accepts assignments made by members with the configured Trusted Provider Manager or Sales Staff role. The authenticated SuperProfile webhook remains a trusted legacy source. Arbitrary role assignments are rejected and do not grant access.
- After approval, the buyer selects YouTube, Instagram or Sales Team as the attribution source. The bot creates a Server B invite with a 24-hour expiry and one maximum use, sends it by DM first, and falls back to the private ticket if DMs are closed.
- When the buyer joins Server B using the tracked invite, the bot assigns the configured Server B mentorship role and deletes the completed purchase ticket. Invite attribution is checked against the intended Discord user. If Discord invite usage cannot be uniquely identified, the bot does not grant the role automatically.
- Removing the required mentorship role in Server A triggers an immediate Server B kick and renewal instructions. A 20-minute reconciliation task catches missed role-removal events or members who leave Server A. The bot does not calculate membership expiry. Invite-use attribution relies on Manage Server permissions and Discord invite usage data; ambiguous join events are held for staff investigation rather than granting access.
- Purchase/renewal tickets have a Close ticket button. Ticket categories automatically roll over before reaching Discord's category channel limit.
- Role assignment and revocation logs remain in their separate configured channels. Sales logs include Discord identity, payment email when available, provider/staff actor and attribution details.
- Removing the configured membership role triggers offboarding from Server B and sends renewal instructions. The bot does not calculate membership expiry.
- /broadcast sends to text channels in a category. Its mention_users option controls whether user mentions are allowed; role and @everyone mentions remain disabled.

## SuperProfile integration

The bot exposes an authenticated relay endpoint for Pabbly's SuperProfile triggers. Pabbly lists Purchase Successful and Subscription Expired as SuperProfile trigger events. On a successful purchase, the authenticated webhook assigns the configured payment-verified role in Server A and marks that assignment as a trusted provider event. The buyer then completes the attribution buttons before the one-use 24-hour Server B invite is issued. On a subscription-expired event, the webhook removes the role; the role-revocation workflow removes the member from Server B. The bot does not calculate membership expiry.

Set this Railway environment variable to a long random secret (do not put it in GitHub or chat):

- SUPERPROFILE_WEBHOOK_SECRET: shared secret used to authenticate Pabbly requests.

Railway supplies PORT automatically. The endpoint is:

https://YOUR-RAILWAY-DOMAIN/webhooks/superprofile

Configure two Pabbly workflows. For each, select SuperProfile-Connect as the trigger app:

1. Purchase Successful → Webhook/API POST action.
2. Subscription Expired → Webhook/API POST action.

For each POST action:
- URL: the Railway endpoint above.
- Header: Authorization: Bearer YOUR_SUPERPROFILE_WEBHOOK_SECRET.
- Content type: application/json.
- Map the trigger's unique transaction/event ID into event_id.
- Map the configured Server A numeric ID into server_a_id.
- Map the buyer's numeric Discord user ID into discord_user_id (recommended). If checkout only collects a Discord username, map it to discord_username; the bot accepts only one exact match and rejects ambiguous names.
- Map the buyer email to email for purchase events.

Purchase body shape:

~~~json
{
  "event": "purchase_successful",
  "event_id": "UNIQUE_PURCHASE_OR_TRANSACTION_ID",
  "server_a_id": "YOUR_SERVER_A_ID",
  "discord_user_id": "BUYER_DISCORD_USER_ID",
  "email": "BUYER_EMAIL"
}
~~~

Expiry body shape:

~~~json
{
  "event": "subscription_expired",
  "event_id": "UNIQUE_EXPIRY_EVENT_ID",
  "server_a_id": "YOUR_SERVER_A_ID",
  "discord_user_id": "BUYER_DISCORD_USER_ID"
}
~~~

The event value is fixed text in each Pabbly action; map the remaining values from the SuperProfile trigger fields. Use a unique event_id for each event. The bot ignores duplicate event IDs and rejects requests without the shared secret. Test with a low-value/test purchase first.

The webhook also accepts an exact discord_username, but numeric Discord user IDs are safer because usernames and display names can be ambiguous.


## 1. Discord application and permissions

Enable these privileged intents in the Discord Developer Portal:
- Server Members Intent
- Message Content Intent

Invite the bot to Server A and Server B. The bot needs:

**Server A**
- View Channels, Send Messages, Embed Links, Read Message History
- View Audit Log (so the bot can identify who assigned the mentorship role)
- Manage Channels, Manage Roles
- Access to the configured ticket categories and log channels

**Server B**
- View Channels, Create Instant Invite, Manage Server (to inspect invite usage), Manage Roles, Kick Members


Place the bot's highest role above the mentorship role in both servers. In Server A, grant View Audit Log. Keep the bot's permissions and trusted staff roles restricted.

## 2. Hosting and persistent database

Install dependencies with: python -m pip install -r requirements.txt

Start the bot with: python main.py

Environment variables:
- DISCORD_TOKEN: bot token (secret)
- DB_PATH: SQLite database path (recommended on Railway: /app/data/bot.sqlite3)
- LOG_LEVEL: optional, defaults to INFO
- SUPERPROFILE_WEBHOOK_SECRET: required to enable the SuperProfile webhook receiver

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
9. Optional ticket staff role ID
10. Trusted Provider Manager role ID
11. Sales Staff role ID
12. Server B mentorship role ID

Copy IDs with Discord Developer Mode enabled. The bot validates the configured channels, roles, Server B membership, invite-tracking permissions and role hierarchy. Both trusted staff roles and the Server B mentorship role are required. Then run /setup_status to inspect saved configuration.

Next, run /mentorship_panel and select the public purchase-panel channel.

## 4. Test purchase procedure

Use a test account and test payment method first:
1. Click Purchase Mentorship and submit the payment email.
2. Confirm a private ticket is created and only the buyer/staff can view it.
3. Click Get membership link and confirm the single checkout link is shown.
4. Upload a test receipt image.
5. Confirm the screenshot embed is forwarded to the sales log.
6. Have a member with the configured Trusted Provider Manager or Sales Staff role assign the Server A mentorship role.
7. Confirm an arbitrary untrusted role assignment is rejected and does not issue an invite.
8. Confirm the approved buyer is asked for attribution and receives a one-use invite that expires after 24 hours (DM first, ticket fallback).
9. Join Server B with the buyer account using that invite. Confirm the Server B mentorship role is assigned and the purchase ticket is deleted.
10. Remove the Server A mentorship role and confirm the Server B member is kicked and renewal instructions are delivered.
11. Test the SuperProfile webhook separately to confirm the existing provider integration still works.

## Commands

| Command | Purpose |
|---|---|
| /setup | Configure Server A/B, role, categories, channels and checkout links (Administrator) |
| /setup_status | Show saved setup status (Administrator) |
| /mentorship_panel | Post the purchase panel (Administrator) |
| /membership_status | Check whether the configured membership role is assigned (Manage Roles) |
| /close_ticket | Close and delete the current registered ticket (Manage Channels) |
| /broadcast | Broadcast to accessible text channels (Administrator) |

Ticket owners can also use the Close ticket button. Only trusted role assignments or authenticated SuperProfile purchase events verify payment. Buyers must submit attribution before receiving their Server B invitation.

## Practical limitations and operations

- Discord role changes and ticket actions require the bot to be online.
- The SuperProfile webhook requires a Pabbly workflow and SUPERPROFILE_WEBHOOK_SECRET in Railway; the code does not connect to your Pabbly account or create workflows automatically.
- If a customer leaves Server A before a renewal ticket can be created, the bot posts a staff alert in the sales channel instead.
- Never commit .env, bot tokens, webhook secrets or the SQLite database. Rotate the Discord token immediately if it is exposed.
