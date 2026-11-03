from __future__ import annotations

import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from database import BotDatabase, utc_now


class BotDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = BotDatabase(str(Path(self.temp_dir.name) / "test.sqlite3"))
        await self.database.initialize()

    async def asyncTearDown(self) -> None:
        await self.database.close()
        self.temp_dir.cleanup()

    async def test_settings_round_trip(self) -> None:
        await self.database.set_setting("staff_role_id", "123456")
        self.assertEqual(await self.database.get_setting("staff_role_id"), "123456")
        self.assertEqual(await self.database.get_setting("missing", "fallback"), "fallback")

    async def test_invitation_ticket_lifecycle(self) -> None:
        ticket_id = await self.database.create_ticket(100, 200, 300, "invitation")
        self.assertGreater(ticket_id, 0)
        tickets = await self.database.get_open_tickets_for_user(100, 300)
        self.assertEqual(len(tickets), 1)
        self.assertEqual(tickets[0]["ticket_type"], "invitation")
        self.assertTrue(await self.database.close_ticket(200))
        self.assertFalse(await self.database.close_ticket(200))
        self.assertEqual(await self.database.get_open_tickets_for_user(100, 300), [])

    async def test_expired_subscription_query(self) -> None:
        now = utc_now()
        await self.database.upsert_subscription(
            100, 300, started_at=now - timedelta(days=30),
            expires_at=now - timedelta(minutes=1), active=True,
        )
        expired = await self.database.list_expired_subscriptions(now=now)
        self.assertEqual(len(expired), 1)
        self.assertEqual(expired[0]["user_id"], 300)

    async def test_upgrade_from_previous_ticket_schema(self) -> None:
        old_dir = tempfile.TemporaryDirectory()
        old_path = Path(old_dir.name) / "old.sqlite3"
        import aiosqlite
        connection = await aiosqlite.connect(old_path)
        await connection.execute("""
            CREATE TABLE tickets (
                ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL UNIQUE,
                user_id INTEGER NOT NULL,
                ticket_type TEXT NOT NULL
                    CHECK (ticket_type IN ('support', 'purchase', 'renewal')),
                status TEXT NOT NULL DEFAULT 'open'
                    CHECK (status IN ('open', 'closed')),
                created_at TEXT NOT NULL,
                closed_at TEXT
            )
        """)
        await connection.execute(
            "CREATE INDEX idx_tickets_user_status ON tickets(user_id, status)"
        )
        await connection.commit()
        await connection.close()

        upgraded = BotDatabase(str(old_path))
        await upgraded.initialize()
        try:
            ticket_id = await upgraded.create_ticket(100, 201, 301, "invitation")
            self.assertGreater(ticket_id, 0)
        finally:
            await upgraded.close()
            old_dir.cleanup()

    async def test_ticket_type_validation(self) -> None:
        with self.assertRaises(ValueError):
            await self.database.create_ticket(100, 201, 300, "unknown")


if __name__ == "__main__":
    unittest.main()
