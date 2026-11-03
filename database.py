import aiosqlite
from typing import Any

DB_PATH = "bot.sqlite3"
SCHEMA = """
CREATE TABLE IF NOT EXISTS guild_config (
 guild_id INTEGER PRIMARY KEY, server_a_id INTEGER, server_b_id INTEGER,
 server_c_id INTEGER, mentorship_role_id INTEGER, sales_channel_id INTEGER,
 audit_channel_id INTEGER, ticket_category_id INTEGER, renewal_category_id INTEGER,
 log_channel_id INTEGER, renewal_url TEXT, subscription_days INTEGER NOT NULL DEFAULT 30,
 panel_channel_id INTEGER, panel_message_id INTEGER
);
CREATE TABLE IF NOT EXISTS subscriptions (
 user_id INTEGER NOT NULL, guild_a_id INTEGER NOT NULL, started_at TEXT NOT NULL,
 expires_at TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
 PRIMARY KEY(user_id, guild_a_id)
);
CREATE TABLE IF NOT EXISTS tickets (
 channel_id INTEGER PRIMARY KEY, guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
 ticket_type TEXT NOT NULL, verified_email TEXT, created_at TEXT NOT NULL,
 approved_at TEXT, closed_at TEXT
);
"""

async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        columns = {row[1] for row in await (await db.execute("PRAGMA table_info(tickets)")).fetchall()}
        for name in ("approved_at", "closed_at"):
            if name not in columns:
                await db.execute(f"ALTER TABLE tickets ADD COLUMN {name} TEXT")
        await db.commit()

async def get_config(guild_id: int) -> dict[str, Any] | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM guild_config WHERE guild_id=?", (guild_id,))
        row = await cur.fetchone()
        return dict(row) if row else None

async def set_config(guild_id: int, **values: Any) -> None:
    allowed = {"server_a_id","server_b_id","server_c_id","mentorship_role_id",
      "sales_channel_id","audit_channel_id","ticket_category_id","renewal_category_id",
      "log_channel_id","renewal_url","subscription_days","panel_channel_id","panel_message_id"}
    values = {k:v for k,v in values.items() if k in allowed}
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO guild_config(guild_id) VALUES(?)", (guild_id,))
        if values:
            cols = ", ".join(f"{k}=?" for k in values)
            await db.execute(f"UPDATE guild_config SET {cols} WHERE guild_id=?", (*values.values(), guild_id))
        await db.commit()

async def save_subscription(user_id: int, guild_a_id: int, days: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""INSERT INTO subscriptions
          (user_id,guild_a_id,started_at,expires_at,active)
          VALUES(?,?,datetime('now'),datetime('now', ?),1)
          ON CONFLICT(user_id,guild_a_id) DO UPDATE SET
          started_at=datetime('now'), expires_at=datetime('now', ?), active=1""",
          (user_id, guild_a_id, f"+{days} days", f"+{days} days"))
        await db.commit()

async def deactivate_subscription(user_id: int, guild_a_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE subscriptions SET active=0 WHERE user_id=? AND guild_a_id=?", (user_id, guild_a_id))
        await db.commit()

async def expired_subscriptions(guild_a_id: int) -> list[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""SELECT user_id FROM subscriptions
          WHERE guild_a_id=? AND active=1 AND expires_at<=datetime('now')""", (guild_a_id,))
        return [int(row[0]) for row in await cur.fetchall()]

async def add_ticket(channel_id: int, guild_id: int, user_id: int, ticket_type: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""INSERT OR REPLACE INTO tickets
          (channel_id,guild_id,user_id,ticket_type,created_at,approved_at,closed_at)
          VALUES(?,?,?,?,datetime('now'),NULL,NULL)""", (channel_id,guild_id,user_id,ticket_type))
        await db.commit()

async def get_ticket(channel_id: int) -> dict[str, Any] | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM tickets WHERE channel_id=?", (channel_id,))
        row = await cur.fetchone()
        return dict(row) if row else None

async def find_open_ticket(guild_id: int, user_id: int, ticket_type: str) -> int | None:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""SELECT channel_id FROM tickets
          WHERE guild_id=? AND user_id=? AND ticket_type=? AND closed_at IS NULL
          ORDER BY created_at DESC LIMIT 1""", (guild_id,user_id,ticket_type))
        row = await cur.fetchone()
        return int(row[0]) if row else None

async def verify_ticket(channel_id: int, email: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE tickets SET verified_email=? WHERE channel_id=?", (email,channel_id))
        await db.commit()

async def approve_ticket(channel_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE tickets SET approved_at=datetime('now') WHERE channel_id=? AND approved_at IS NULL", (channel_id,))
        await db.commit()

async def close_ticket(channel_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE tickets SET closed_at=datetime('now') WHERE channel_id=?", (channel_id,))
        await db.commit()
