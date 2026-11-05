import os
import tempfile
import unittest

import database

class DatabaseWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.original_path = database.DB_PATH
        self.temp_dir = tempfile.TemporaryDirectory()
        database.DB_PATH = os.path.join(self.temp_dir.name, "test.sqlite3")
        await database.init_db()

    async def asyncTearDown(self):
        database.DB_PATH = self.original_path
        self.temp_dir.cleanup()

    async def test_ticket_review_is_claimed_once(self):
        await database.add_ticket(111, 222, 333, "purchase", "buyer@example.com")
        self.assertTrue(await database.claim_ticket_review(111))
        self.assertFalse(await database.claim_ticket_review(111))
        await database.finish_ticket_approval(111, "buyer@example.com", "30 days")
        ticket = await database.get_ticket(111)
        self.assertEqual(ticket["approval_status"], "approved")
        self.assertEqual(ticket["verified_email"], "buyer@example.com")
        self.assertEqual(ticket["tenure"], "30 days")

    async def test_failed_review_can_be_retried(self):
        await database.add_ticket(112, 222, 333, "purchase", "buyer@example.com")
        self.assertTrue(await database.claim_ticket_review(112))
        await database.release_ticket_review(112)
        self.assertTrue(await database.claim_ticket_review(112))

    async def test_subscription_term_and_inactive_lookup(self):
        await database.save_subscription(333, 222, 30, "30 days", "buyer@example.com")
        active = await database.get_subscription(333, 222)
        self.assertIsNotNone(active)
        self.assertEqual(active["tenure"], "30 days")
        self.assertEqual(active["email"], "buyer@example.com")
        self.assertEqual(active["active"], 1)
        await database.deactivate_subscription(333, 222)
        inactive = await database.get_subscription(333, 222)
        self.assertEqual(inactive["active"], 0)

    async def test_90_day_subscription_term(self):
        await database.save_subscription(444, 222, 90, "90 days", "long@example.com")
        active = await database.get_subscription(444, 222)
        self.assertEqual(active["tenure"], "90 days")
        self.assertEqual(active["active"], 1)

    async def test_invalid_subscription_term_rejected(self):
        with self.assertRaises(ValueError):
            await database.save_subscription(333, 222, 45, "45 days", None)
        with self.assertRaises(ValueError):
            await database.save_subscription(333, 222, 90, "30 days", None)

if __name__ == "__main__":
    unittest.main()
