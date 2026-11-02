# Reveals Bot Management

Multi-server Discord bot starter using Node.js 22+, discord.js v14 and SQLite.

## Features
- Mentorship role verification against Server A as the authority.
- Scheduled membership expiration checks; inconclusive API checks never trigger removal.
- Renewal DM with private ticket fallback.
- Slash commands: `/broadcast`, `/membership-check`, `/renewal-complete`, `/ticket-close`.
- Mentorship role audit logging and moderation-event forwarding to Server C.
- SQLite membership, ticket, audit, and job-run tables.

## Setup
1. Create a Discord application and bot.
2. Enable **Server Members Intent** in the Developer Portal.
3. Copy `.env.example` to `.env` and fill in IDs/token.
4. Run `npm install`, `npm run db:init`, `npm run deploy`, then `npm start`.

Never commit `.env` or share your bot token. Required permissions and role hierarchy are listed below.

## Required configuration
Server A: View Channels, Send Messages, Embed Links, View Audit Log, Manage Channels.
Server B: View Channels, Kick Members, Create Instant Invite.
Server C: View Channel, Send Messages, Embed Links in the log channel.

## Production caveats
This starter does not integrate with a payment processor. A trusted payment workflow must grant the Server A role and create/update the membership row including `expires_at`. Audit-log executor attribution is best-effort. Test on a non-critical account before enabling automatic offboarding. Use one scheduler instance with SQLite.
