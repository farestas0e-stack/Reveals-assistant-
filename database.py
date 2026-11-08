import os
from typing import Any
import aiosqlite

DB_PATH = os.getenv("DB_PATH", "bot.sqlite3")

SCHEMA = """
CREATE TABLE IF NOT EXISTS guild_config (
 guild_id INTEGER PRIMARY KEY, server_a_id INTEGER, server_b_id INTEGER,
 server_c_id INTEGER, mentorship_role_id INTEGER, sales_channel_id INTEGER,
 audit_channel_id INTEGER, role_assigned_channel_id INTEGER, role_revoked_channel_id INTEGER,
 ticket_category_id INTEGER, renewal_category_id INTEGER, log_channel_id INTEGER,
 ticket_log_channel_id INTEGER,
 renewal_url TEXT, subscription_days INTEGER NOT NULL DEFAULT 30,
 panel_channel_id INTEGER, panel_message_id INTEGER,
 monthly_url TEXT, staff_role_id INTEGER
);
CREATE TABLE IF NOT EXISTS subscriptions (
 user_id INTEGER NOT NULL, guild_a_id INTEGER NOT NULL, started_at TEXT NOT NULL,
 expires_at TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
 tenure TEXT NOT NULL DEFAULT 'monthly', email TEXT,
 PRIMARY KEY(user_id, guild_a_id)
);
CREATE TABLE IF NOT EXISTS provider_webhook_events (
 provider TEXT NOT NULL, event_id TEXT NOT NULL, event_type TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'processing', received_at TEXT NOT NULL DEFAULT (datetime('now')),
 PRIMARY KEY(provider, event_id)
);
CREATE TABLE IF NOT EXISTS tickets (
 channel_id INTEGER PRIMARY KEY, guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
 ticket_type TEXT NOT NULL, submitted_email TEXT, verified_email TEXT,
 created_at TEXT NOT NULL, approved_at TEXT, closed_at TEXT, tenure TEXT,
 evidence_message_id INTEGER, approval_status TEXT NOT NULL DEFAULT 'pending'
);
CREATE TABLE IF NOT EXISTS category_removal_usage (
 guild_id INTEGER PRIMARY KEY,
 uses INTEGER NOT NULL DEFAULT 0
);
"""

async def _columns(db, table: str) -> set[str]:
    rows = await (await db.execute(f"PRAGMA table_info({table})")).fetchall()
    return {row[1] for row in rows}

async def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        migrations = {
            "guild_config": {
                "monthly_url": "TEXT", "staff_role_id": "INTEGER",
                "role_assigned_channel_id": "INTEGER", "role_revoked_channel_id": "INTEGER",
                "renewal_url": "TEXT", "server_c_id": "INTEGER", "log_channel_id": "INTEGER", "ticket_log_channel_id": "INTEGER"
            },
            "subscriptions": {"tenure": "TEXT NOT NULL DEFAULT 'monthly'", "email": "TEXT"},
            "tickets": {
                "submitted_email": "TEXT", "verified_email": "TEXT", "approved_at": "TEXT",
                "closed_at": "TEXT", "tenure": "TEXT", "evidence_message_id": "INTEGER",
                "approval_status": "TEXT NOT NULL DEFAULT 'pending'"
            }
        }
        for table, wanted in migrations.items():
            existing = await _columns(db, table)
            for name, definition in wanted.items():
                if name not in existing:
                    await db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
        await db.commit()

async def get_config(guild_id: int) -> dict[str, Any] | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        row = await (await db.execute("SELECT * FROM guild_config WHERE guild_id=?", (guild_id,))).fetchone()
        return dict(row) if row else None

async def set_config(guild_id: int, **values: Any) -> None:
    allowed = {
        "server_a_id", "server_b_id", "server_c_id", "mentorship_role_id",
        "sales_channel_id", "audit_channel_id", "role_assigned_channel_id",
        "role_revoked_channel_id", "ticket_category_id", "renewal_category_id",
        "log_channel_id", "renewal_url", "subscription_days", "panel_channel_id",
        "panel_message_id", "monthly_url", "staff_role_id", "ticket_log_channel_id"
    }
    values = {key: value for key, value in values.items() if key in allowed}
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO guild_config(guild_id) VALUES(?)", (guild_id,))
        if values:
            assignments = ", ".join(f"{key}=?" for key in values)
            await db.execute(
                f"UPDATE guild_config SET {assignments} WHERE guild_id=?",
                (*values.values(), guild_id)
            )
        await db.commit()

async def claim_category_removal(guild_id: int, limit: int = 3) -> tuple[bool, int]:
    """Atomically consume one of a guild's limited category-removal uses."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("BEGIN IMMEDIATE")
        await db.execute(
            "INSERT OR IGNORE INTO category_removal_usage(guild_id, uses) VALUES(?, 0)",
            (guild_id,)
        )
        row = await (await db.execute(
            "SELECT uses FROM category_removal_usage WHERE guild_id=?",
            (guild_id,)
        )).fetchone()
        used = int(row[0]) if row else 0
        if used >= limit:
            await db.commit()
            return False, used
        used += 1
        await db.execute(
            "UPDATE category_removal_usage SET uses=? WHERE guild_id=?",
            (used, guild_id)
        )
        await db.commit()
        return True, used

async def category_removal_uses(guild_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        row = await (await db.execute(
            "SELECT uses FROM category_removal_usage WHERE guild_id=?",
            (guild_id,)
        )).fetchone()
        return int(row[0]) if row else 0

async def save_subscription(user_id: int, guild_a_id: int, days: int,
                            tenure: str, email: str | None = None) -> None:
    expected_tenure = {30: "30 days", 90: "90 days"}.get(days)
    if expected_tenure is None or tenure != expected_tenure:
        raise ValueError("Membership duration must be exactly 30 or 90 days.")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO subscriptions
                (user_id,guild_a_id,started_at,expires_at,active,tenure,email)
            VALUES(?,?,datetime('now'),datetime('now', ?),1,?,?)
            ON CONFLICT(user_id,guild_a_id) DO UPDATE SET
                started_at=datetime('now'), expires_at=datetime('now', ?),
                active=1, tenure=?, email=?
        """, (user_id, guild_a_id, f"+{days} days", tenure, email,
              f"+{days} days", tenure, email))
        await db.commit()

async def deactivate_subscription(user_id: int, guild_a_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE subscriptions SET active=0 WHERE user_id=? AND guild_a_id=?",
            (user_id, guild_a_id)
        )
        await db.commit()

async def get_subscription(user_id: int, guild_a_id: int) -> dict[str, Any] | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        row = await (await db.execute(
            "SELECT * FROM subscriptions WHERE user_id=? AND guild_a_id=?",
            (user_id, guild_a_id)
        )).fetchone()
        return dict(row) if row else None

async def expired_subscriptions(guild_a_id: int) -> list[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        rows = await (await db.execute(
            "SELECT user_id FROM subscriptions WHERE guild_a_id=? AND active=1 AND expires_at<=datetime('now')",
            (guild_a_id,)
        )).fetchall()
        return [int(row[0]) for row in rows]

async def active_subscriptions(guild_a_id: int) -> list[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await (await db.execute(
            "SELECT * FROM subscriptions WHERE guild_a_id=? AND active=1",
            (guild_a_id,)
        )).fetchall()
        return [dict(row) for row in rows]

async def add_ticket(channel_id: int, guild_id: int, user_id: int,
                     ticket_type: str, email: str | None = None) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO tickets
            (channel_id,guild_id,user_id,ticket_type,submitted_email,created_at,
             approved_at,closed_at,tenure,evidence_message_id,approval_status)
            VALUES(?,?,?,?,?,datetime('now'),NULL,NULL,NULL,NULL,'pending')
        """, (channel_id, guild_id, user_id, ticket_type, email))
        await db.commit()

async def get_ticket(channel_id: int) -> dict[str, Any] | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        row = await (await db.execute(
            "SELECT * FROM tickets WHERE channel_id=?", (channel_id,)
        )).fetchone()
        return dict(row) if row else None

async def find_pending_ticket(guild_id: int, user_id: int) -> dict[str, Any] | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        row = await (await db.execute("""
            SELECT * FROM tickets
            WHERE guild_id=? AND user_id=? AND approval_status='pending'
              AND ticket_type IN ('purchase','renewal')
            ORDER BY created_at DESC LIMIT 1
        """, (guild_id, user_id))).fetchone()
        return dict(row) if row else None

async def find_open_ticket(guild_id: int, user_id: int, kind: str) -> int | None:
    async with aiosqlite.connect(DB_PATH) as db:
        row = await (await db.execute("""
            SELECT channel_id FROM tickets
            WHERE guild_id=? AND user_id=? AND ticket_type=? AND closed_at IS NULL
            ORDER BY created_at DESC LIMIT 1
        """, (guild_id, user_id, kind))).fetchone()
        return int(row[0]) if row else None

async def set_ticket_email(channel_id: int, email: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE tickets SET submitted_email=? WHERE channel_id=?", (email, channel_id))
        await db.commit()

async def set_ticket_tenure(channel_id: int, tenure: str) -> None:
    if tenure not in ("30 days", "90 days"):
        raise ValueError("Membership duration must be exactly 30 or 90 days.")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE tickets SET tenure=? WHERE channel_id=?", (tenure, channel_id))
        await db.commit()

async def set_evidence(channel_id: int, message_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE tickets SET evidence_message_id=? WHERE channel_id=? AND approval_status='pending'",
            (message_id, channel_id)
        )
        await db.commit()

async def claim_ticket_review(channel_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            UPDATE tickets SET approval_status='processing'
            WHERE channel_id=? AND approval_status='pending'
        """, (channel_id,))
        await db.commit()
        return cursor.rowcount == 1

async def finish_ticket_approval(channel_id: int, email: str, tenure: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE tickets SET approved_at=datetime('now'), verified_email=?,
                tenure=?, approval_status='approved'
            WHERE channel_id=? AND approval_status='processing'
        """, (email, tenure, channel_id))
        await db.commit()

async def release_ticket_review(channel_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE tickets SET approval_status='pending' WHERE channel_id=? AND approval_status='processing'",
            (channel_id,)
        )
        await db.commit()

async def reject_ticket(channel_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            UPDATE tickets SET approval_status='rejected'
            WHERE channel_id=? AND approval_status='pending'
        """, (channel_id,))
        await db.commit()
        return cursor.rowcount == 1

async def close_ticket(channel_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE tickets SET closed_at=datetime('now') WHERE channel_id=?",
            (channel_id,)
        )
        await db.commit()


async def claim_provider_event(provider: str, event_id: str, event_type: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            INSERT OR IGNORE INTO provider_webhook_events
                (provider, event_id, event_type, status)
            VALUES(?,?,?,'processing')
        """, (provider, event_id, event_type))
        await db.commit()
        return cursor.rowcount == 1


async def finish_provider_event(provider: str, event_id: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE provider_webhook_events SET status='processed'
            WHERE provider=? AND event_id=?
        """, (provider, event_id))
        await db.commit()


async def release_provider_event(provider: str, event_id: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            DELETE FROM provider_webhook_events
            WHERE provider=? AND event_id=? AND status='processing'
        """, (provider, event_id))
        await db.commit()


async def mark_ticket_access_granted(channel_id: int, email: str | None = None) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE tickets
            SET approved_at=COALESCE(approved_at, datetime('now')),
                verified_email=COALESCE(?, verified_email),
                approval_status='approved'
            WHERE channel_id=?
        """, (email, channel_id))
        await db.commit()
