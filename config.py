"""Fixed Discord IDs supplied for the Mentorship bot.

Staff role, Superprofile URLs, invite channel and moderation destination are
configured inside Discord with slash commands and stored in SQLite.
"""

# Discord server IDs
SERVER_A_ID = 1516875810206646373  # Hub / Mentorship source server
SERVER_B_ID = 1560196497281130527  # Private community
SERVER_C_ID = 1566866397538025552  # Moderation log destination

# Mentorship role in Server A
MENTORSHIP_ROLE_ID = 1548745497831809165

# Server A notification channels
SALES_CHANNEL_ID = 1567100561566998638
ROLE_ASSIGNED_CHANNEL_ID = 1567101070621151362
ROLE_REMOVED_CHANNEL_ID = 1567101157510483969

# Optional legacy fallback. Configure the actual staff role with /setstaffrole.
MODERATOR_ROLE_ID = 0
