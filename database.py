from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("Datetime values must include a timezone.")
    return value.astimezone(timezone.utc).isoformat()


class BotDatabase:
    """Asynchronous SQLite storage for bot settings, subscriptions, tickets and logs."""

    def __init__(self, database_path: str = "data/bot.sqlite3") -> None:
        self.database_path = database_path
        self.connection: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = await aiosqlite.connect(self.database_path)
        self.connection.row_factory = aiosqlite.Row
        await self.connection.execute("PRAGMA foreign_keys = ON")
        await self.connection.execute("PRAGMA journal_mode = WAL")
        await self.connection.execute("PRAGMA busy_timeout = 5000")
        await self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS subscriptions (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                plan_name TEXT NOT NULL DEFAULT 'Mentorship',
                started_at TEXT NOT NULL,
                expires_at TEXT,
                source TEXT NOT NULL DEFAULT 'superprofile',
                active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
                updated_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, user_id)
            );
            CREATE INDEX IF NOT EXISTS idx_subscriptions_expiry
                ON subscriptions(active, expires_at);
            CREATE TABLE IF NOT EXISTS tickets (
                ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL UNIQUE,
                user_id INTEGER NOT NULL,
                ticket_type TEXT NOT NULL
                    CHECK (ticket_type IN ('support', 'purchase', 'renewal', 'invitation')),
                status TEXT NOT NULL DEFAULT 'open'
                    CHECK (status IN ('open', 'closed')),
                created_at TEXT NOT NULL,
                closed_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_tickets_user_status
                ON tickets(user_id, status);
            CREATE TABLE IF NOT EXISTS audit_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                actor_id INTEGER,
                target_id INTEGER,
                event_type TEXT NOT NULL,
                details_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_audit_events_guild_time
                ON audit_events(guild_id, created_at);
        """)
        # Upgrade databases created by the first version, which lacked invitation tickets.
        cursor = await self.connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='tickets'"
        )
        schema_row = await cursor.fetchone()
        await cursor.close()
        if schema_row and "'invitation'" not in (schema_row["sql"] or ""):
            await self.connection.executescript("""
                ALTER TABLE tickets RENAME TO tickets_old;
                CREATE TABLE tickets (
                    ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL UNIQUE,
                    user_id INTEGER NOT NULL,
                    ticket_type TEXT NOT NULL
                        CHECK (ticket_type IN ('support', 'purchase', 'renewal', 'invitation')),
                    status TEXT NOT NULL DEFAULT 'open'
                        CHECK (status IN ('open', 'closed')),
                    created_at TEXT NOT NULL,
                    closed_at TEXT
                );
                INSERT INTO tickets
                    (ticket_id, guild_id, channel_id, user_id, ticket_type, status, created_at, closed_at)
                SELECT ticket_id, guild_id, channel_id, user_id, ticket_type, status, created_at, closed_at
                FROM tickets_old;
                DROP TABLE tickets_old;
                CREATE INDEX IF NOT EXISTS idx_tickets_user_status
                    ON tickets(user_id, status);
            """)
        await self.connection.commit()

    def _db(self) -> aiosqlite.Connection:
        if self.connection is None:
            raise RuntimeError("Database is not initialized.")
        return self.connection

    async def close(self) -> None:
        if self.connection is not None:
            await self.connection.commit()
            await self.connection.close()
            self.connection = None

    async def set_setting(self, key: str, value: str) -> None:
        await self._db().execute("""
            INSERT INTO settings(setting_key, setting_value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(setting_key) DO UPDATE SET
                setting_value=excluded.setting_value, updated_at=excluded.updated_at
        """, (key, value, to_utc_iso(utc_now())))
        await self._db().commit()

    async def get_setting(self, key: str, default: str | None = None) -> str | None:
        cursor = await self._db().execute(
            "SELECT setting_value FROM settings WHERE setting_key = ?", (key,)
        )
        row = await cursor.fetchone()
        await cursor.close()
        return str(row["setting_value"]) if row else default

    async def upsert_subscription(
        self, guild_id: int, user_id: int, *, plan_name: str = "Mentorship",
        started_at: datetime | None = None, expires_at: datetime | None = None,
        source: str = "superprofile", active: bool = True,
    ) -> None:
        now = to_utc_iso(utc_now())
        await self._db().execute("""
            INSERT INTO subscriptions
                (guild_id,user_id,plan_name,started_at,expires_at,source,active,updated_at)
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(guild_id,user_id) DO UPDATE SET
                plan_name=excluded.plan_name, started_at=excluded.started_at,
                expires_at=excluded.expires_at, source=excluded.source,
                active=excluded.active, updated_at=excluded.updated_at
        """, (guild_id, user_id, plan_name, to_utc_iso(started_at or utc_now()),
              to_utc_iso(expires_at) if expires_at else None, source, int(active), now))
        await self._db().commit()

    async def get_subscription(self, guild_id: int, user_id: int) -> dict[str, Any] | None:
        cursor = await self._db().execute(
            "SELECT * FROM subscriptions WHERE guild_id=? AND user_id=?", (guild_id, user_id))
        row = await cursor.fetchone()
        await cursor.close()
        return dict(row) if row else None

    async def list_expired_subscriptions(self, *, now: datetime | None = None) -> list[dict[str, Any]]:
        cursor = await self._db().execute("""
            SELECT * FROM subscriptions WHERE active=1 AND expires_at IS NOT NULL
            AND expires_at <= ? ORDER BY expires_at ASC
        """, (to_utc_iso(now or utc_now()),))
        rows = await cursor.fetchall()
        await cursor.close()
        return [dict(row) for row in rows]

    async def set_subscription_active(self, guild_id: int, user_id: int, active: bool) -> None:
        await self._db().execute("""
            UPDATE subscriptions SET active=?, updated_at=? WHERE guild_id=? AND user_id=?
        """, (int(active), to_utc_iso(utc_now()), guild_id, user_id))
        await self._db().commit()

    async def create_ticket(self, guild_id: int, channel_id: int, user_id: int, ticket_type: str) -> int:
        if ticket_type not in {"support", "purchase", "renewal", "invitation"}:
            raise ValueError("Unsupported ticket type.")
        cursor = await self._db().execute("""
            INSERT INTO tickets(guild_id,channel_id,user_id,ticket_type,created_at)
            VALUES (?,?,?,?,?)
        """, (guild_id, channel_id, user_id, ticket_type, to_utc_iso(utc_now())))
        await self._db().commit()
        ticket_id = int(cursor.lastrowid)
        await cursor.close()
        return ticket_id

    async def get_open_ticket_for_user(self, guild_id: int, user_id: int) -> dict[str, Any] | None:
        cursor = await self._db().execute("""
            SELECT * FROM tickets WHERE guild_id=? AND user_id=? AND status='open'
            ORDER BY created_at DESC LIMIT 1
        """, (guild_id, user_id))
        row = await cursor.fetchone()
        await cursor.close()
        return dict(row) if row else None

    async def get_open_tickets_for_user(self, guild_id: int, user_id: int) -> list[dict[str, Any]]:
        cursor = await self._db().execute("""
            SELECT * FROM tickets WHERE guild_id=? AND user_id=? AND status='open'
            ORDER BY created_at DESC
        """, (guild_id, user_id))
        rows = await cursor.fetchall()
        await cursor.close()
        return [dict(row) for row in rows]

    async def close_ticket(self, channel_id: int) -> bool:
        cursor = await self._db().execute("""
            UPDATE tickets SET status='closed', closed_at=?
            WHERE channel_id=? AND status='open'
        """, (to_utc_iso(utc_now()), channel_id))
        await self._db().commit()
        changed = cursor.rowcount > 0
        await cursor.close()
        return changed

    async def add_audit_event(
        self, guild_id: int, event_type: str, *, actor_id: int | None = None,
        target_id: int | None = None, details: dict[str, Any] | None = None,
    ) -> None:
        await self._db().execute("""
            INSERT INTO audit_events(guild_id,actor_id,target_id,event_type,details_json,created_at)
            VALUES (?,?,?,?,?,?)
        """, (guild_id, actor_id, target_id, event_type,
              json.dumps(details or {}, ensure_ascii=False), to_utc_iso(utc_now())))
        await self._db().commit()
