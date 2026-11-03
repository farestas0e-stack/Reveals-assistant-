# Reveals Assistant Discord Bot

A Python 3.10+ Discord bot for a three-server Mentorship membership workflow.

## Technology

- Python 3.10+
- discord.py 2.x
- asyncio
- aiosqlite / SQLite

## Servers

The server IDs and fixed notification channel IDs are stored in `config.py`.

- Server A: Hub / Mentorship role source and ticket home.
- Server B: Private community.
- Server C: Moderation log destination.

The bot must be invited to all three servers.

## Install

1. Install Python 3.10 or newer.
2. Download or clone this repository.
3. Open a terminal in the project folder.
4. Install dependencies:

   ```bash
   python -m pip install -r requirements.txt
   ```

5. Set the bot token as an environment variable named `DISCORD_BOT_TOKEN`.
   - Windows PowerShell: `$env:DISCORD_BOT_TOKEN="YOUR_TOKEN"`
   - macOS/Linux: `export DISCORD_BOT_TOKEN="YOUR_TOKEN"`

   Never commit the bot token to GitHub or paste it into a public channel.

6. Start the bot:

   ```bash
   python main.py
   ```

The SQLite database is created automatically at `data/bot.sqlite3`. Keep this folder on persistent storage when hosting the bot.

## Discord Developer Portal

In the bot application's **Bot** settings, enable:

- Server Members Intent
- Message Content Intent

The bot uses member events to detect Mentorship role changes and member joins. Message Content Intent is used for deleted-message logging when the deleted message is available in Discord.py's message cache.

## Required permissions

Do not grant Administrator unless you deliberately prefer that. Grant the following minimum permissions and confirm the bot's role is high enough in the Server B role list to kick members:

### Server A
- View Channels
- Send Messages
- Embed Links
- Read Message History
- Manage Channels (create and delete private ticket channels/categories)
- View Audit Log (identify role-change actors and moderation actors)

### Server B
- View Channels
- Create Instant Invite
- Kick Members
- Manage Roles (only if you configure a separate Server B access role)

### Server C
- View Channel
- Send Messages
- Embed Links

The bot does not assign the Mentorship role. Your external Superprofile/admin workflow assigns or removes that role in Server A.

## First-time Discord setup

Run these commands as a server administrator.

### In Server A

1. `/setstaffrole role:<your staff role>`
2. `/setlink link_type:Purchase / checkout url:<your checkout URL>`
3. `/setlink link_type:Renewal url:<your renewal URL>`
4. `/createpanel` in the channel where the public ticket panel should appear.
5. For each member with a known expiry, run `/setmembershipexpiry member:<member> expiry_iso:<UTC ISO timestamp>`.

Example expiry value: `2027-12-31T23:59:00+00:00`.

### In Server B

1. Run `/setcommunityrole role:<private community access role>` to grant the member role after verifying their Server A Mentorship role. The bot needs Manage Roles and its highest role must be above the selected role.\n2. Optionally run `/setinvitechannel channel:<invite channel>`.
3. If no channel is selected, the bot searches for a text channel where it has View Channel and Create Instant Invite permissions.

### In Server C

1. Run `/setmoderationchannel channel:<log channel>`.

### Verify setup

Run `/setup`, `/setupstatus` and `/healthcheck`.

## Membership workflow

- When the Mentorship role is added in Server A, the bot records/reactivates the subscription, posts Sales and role-assigned notifications, closes any renewal ticket, and sends a fresh one-use Server B invitation.
- If the invitation cannot be generated or delivered by DM, the bot creates a private Invitation Ticket in Server A. When an invite URL exists, it posts the URL there; if Discord prevents invite creation, the ticket tells staff that manual help is required.
- When a ticket creator joins Server B, the bot checks that the member still has the Mentorship role in Server A, grants the configured Server B access role (if one is configured), and deletes their Purchase/Invitation/Renewal ticket after access setup succeeds. Ineligible joiners are kicked from Server B and their ticket is not deleted.
- When the role is removed, the bot logs the change but leaves a recorded expiry job active. At expiry, the bot checks the Server A role again. If it is still present, access is preserved. If absent, the bot removes the member from Server B, sends the renewal URL by DM, and creates a private Renewal Ticket if the DM fails.
- A role re-added after removal triggers the invitation workflow again.
- If the bot missed a role event while offline, an administrator can run `/syncmember member:<member>`.
- If a renewal occurs while the role never changes, an administrator can run `/recordrenewal member:<member> expiry_iso:<UTC ISO timestamp>`.

**Important:** Membership expiration dates are not provided by Discord role changes. Record them with `/setmembershipexpiry` or `/recordrenewal`, or have your external admin workflow maintain the database. Superprofile payment processing itself is external; this bot uses the URLs you configure and reacts to role changes.

## Ticket and panel commands

- `/createpanel` — create the persistent Support/Purchase/Renewal panel.
- `/editpanel` — edit title, description and color together.
- `/settitle`, `/setdescription`, `/setcolor` — edit individual embed fields.
- `/setbutton` — change a button label.
- `/refreshpanel` — apply the current persistent buttons to the saved panel.
- `/deletepanel` — delete the saved panel.
- `/closeticket` — staff/admin delete the current ticket.
- `/closemyticket` — ticket creator deletes their own ticket.
- Ticket categories are created automatically and expanded at 49 channels.

## Other admin commands

- `/broadcast category:<category> message:<message>` — send to text channels in a category where the bot can view and send.
- `/setstaffrole`, `/setlink`, `/setinvitechannel`, `/setcommunityrole`, `/setmoderationchannel`
- `/setmembershipexpiry`, `/recordrenewal`, `/syncmember`, `/healthcheck`

## Important operational notes

- One-use Discord invites are not identity-bound. A recipient can forward an invite, but Server B join checks still reject anyone who does not currently have the Mentorship role in Server A.
- The bot must remain online for event-driven notifications and periodic expiry checks. The expiry worker checks every 15 minutes.
- Keep the SQLite database on persistent storage and back it up.
- If a user cannot be found in Server A, the bot cannot create a private ticket for them there.
- Discord permissions, role hierarchy, channel visibility and server membership are controlled by Discord. Test in a private test channel/server before relying on the bot for live memberships.
