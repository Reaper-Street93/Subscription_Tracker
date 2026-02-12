import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import server


class ServerLogicTests(unittest.TestCase):
    def setUp(self) -> None:
        self._original_db_path = server.DB_PATH
        self._tmpdir = tempfile.TemporaryDirectory()
        server.DB_PATH = Path(self._tmpdir.name) / "test_subscriptions.db"
        server.init_db()

    def tearDown(self) -> None:
        server.DB_PATH = self._original_db_path
        self._tmpdir.cleanup()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(server.DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    def test_init_db_creates_required_tables(self) -> None:
        with self._connect() as conn:
            tables = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }

        self.assertIn("users", tables)
        self.assertIn("sessions", tables)
        self.assertIn("subscriptions", tables)
        self.assertIn("categories", tables)
        self.assertIn("login_rate_limits", tables)

    def test_hash_and_verify_password(self) -> None:
        hashed = server.hash_password("password123")
        self.assertTrue(server.verify_password("password123", hashed))
        self.assertFalse(server.verify_password("wrong-password", hashed))

    def test_parse_auth_payload_validates_input(self) -> None:
        payload, err = server.parse_auth_payload(
            {"name": "Jane", "email": "jane@example.com", "password": "password123"},
            require_name=True,
        )
        self.assertIsNone(err)
        self.assertEqual(payload["email"], "jane@example.com")

        payload, err = server.parse_auth_payload(
            {"email": "bad", "password": "short"},
            require_name=False,
        )
        self.assertIsNone(payload)
        self.assertEqual(err, "A valid email is required")

    def test_parse_password_reset_payload_validates_input(self) -> None:
        payload, err = server.parse_password_reset_payload(
            {"email": "jane@example.com", "newPassword": "newpassword123"}
        )
        self.assertIsNone(err)
        self.assertEqual(payload["email"], "jane@example.com")

        payload, err = server.parse_password_reset_payload(
            {"email": "bad", "newPassword": "short"}
        )
        self.assertIsNone(payload)
        self.assertEqual(err, "A valid email is required")

    def test_subscription_payload_and_monthly_cost(self) -> None:
        payload, err = server.parse_subscription_payload(
            {
                "name": "Notion",
                "category": " Productivity  ",
                "amount": 120,
                "billingCycle": "yearly",
                "nextPaymentDate": "2026-02-20",
            }
        )
        self.assertIsNone(err)
        self.assertEqual(payload["category"], "Productivity")
        self.assertEqual(server.monthly_cost(payload["amount"], payload["billing_cycle"]), 10.0)

        payload, err = server.parse_subscription_payload(
            {
                "name": "",
                "category": "Streaming",
                "amount": 10,
                "billingCycle": "monthly",
                "nextPaymentDate": "2026-02-20",
            }
        )
        self.assertIsNone(payload)
        self.assertEqual(err, "Subscription name is required")

    def test_next_due_date_rolls_forward(self) -> None:
        due = server.next_due_date(date(2025, 12, 15), "monthly", today=date(2026, 2, 12))
        self.assertEqual(due.isoformat(), "2026-02-15")

        yearly_due = server.next_due_date(date(2025, 2, 1), "yearly", today=date(2026, 2, 12))
        self.assertEqual(yearly_due.isoformat(), "2027-02-01")

    def test_seed_default_categories_and_ensure_category(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
                ("Test User", "cat@example.com", server.hash_password("password123"), server.utc_now_iso()),
            )
            user_id = conn.execute(
                "SELECT id FROM users WHERE email = ?", ("cat@example.com",)
            ).fetchone()["id"]

            server.seed_default_categories(conn, int(user_id))
            server.seed_default_categories(conn, int(user_id))
            rows = conn.execute(
                "SELECT name FROM categories WHERE user_id = ?",
                (int(user_id),),
            ).fetchall()
            self.assertGreaterEqual(len(rows), len(server.DEFAULT_CATEGORIES))

            server.ensure_category_exists(conn, int(user_id), "Gaming")
            server.ensure_category_exists(conn, int(user_id), "gaming")
            count = conn.execute(
                "SELECT COUNT(*) AS count FROM categories WHERE user_id = ? AND name = ? COLLATE NOCASE",
                (int(user_id), "Gaming"),
            ).fetchone()["count"]
            self.assertEqual(count, 1)

    def test_issue_session_persists_hashed_token(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
                ("Session User", "session@example.com", server.hash_password("password123"), server.utc_now_iso()),
            )
            user_id = conn.execute(
                "SELECT id FROM users WHERE email = ?", ("session@example.com",)
            ).fetchone()["id"]

            token = server.issue_session(conn, int(user_id))
            token_hash = server.hash_session_token(token)
            row = conn.execute(
                "SELECT token_hash, expires_at, last_seen_at FROM sessions WHERE user_id = ?",
                (int(user_id),),
            ).fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(row["token_hash"], token_hash)
        expires_at = datetime.fromisoformat(row["expires_at"])
        self.assertGreater(expires_at, datetime.utcnow())
        self.assertIsNotNone(row["last_seen_at"])

    def test_csrf_pair_validation(self) -> None:
        self.assertTrue(server.is_valid_csrf_pair("token-1", "token-1"))
        self.assertFalse(server.is_valid_csrf_pair("token-1", "token-2"))
        self.assertFalse(server.is_valid_csrf_pair("", "token-1"))
        self.assertFalse(server.is_valid_csrf_pair("token-1", None))

    def test_cookie_header_respects_secure_flag(self) -> None:
        with patch.dict("os.environ", {"COOKIE_SECURE": "0"}, clear=False):
            header = server.build_cookie_header("name", "value", max_age=120, http_only=True)
            self.assertIn("HttpOnly", header)
            self.assertNotIn("Secure", header)

        with patch.dict("os.environ", {"COOKIE_SECURE": "1"}, clear=False):
            header = server.build_cookie_header("name", "value", max_age=120, http_only=False)
            self.assertIn("Secure", header)
            self.assertNotIn("HttpOnly", header)

    def test_login_rate_limit_persists_and_expires(self) -> None:
        key = "127.0.0.1|user@example.com"
        now = datetime(2026, 2, 12, 12, 0, 0)

        with self._connect() as conn:
            limited, retry = server.check_login_rate_limit(conn, key, now=now)
            self.assertFalse(limited)
            self.assertEqual(retry, 0)

            for i in range(server.LOGIN_MAX_ATTEMPTS - 1):
                lock_seconds = server.register_login_failure(conn, key, now=now + timedelta(seconds=i))
                self.assertEqual(lock_seconds, 0)

            lock_seconds = server.register_login_failure(conn, key, now=now + timedelta(seconds=20))
            self.assertGreater(lock_seconds, 0)

        # Confirm lock state persists when reading from a fresh DB connection.
        with self._connect() as conn:
            limited, retry = server.check_login_rate_limit(conn, key, now=now + timedelta(seconds=30))
            self.assertTrue(limited)
            self.assertGreater(retry, 0)

            limited, retry = server.check_login_rate_limit(
                conn,
                key,
                now=now + timedelta(seconds=20) + server.LOGIN_LOCKOUT_DURATION + timedelta(seconds=1),
            )
            self.assertFalse(limited)
            self.assertEqual(retry, 0)

    def test_cleanup_login_rate_limits_removes_stale_rows(self) -> None:
        now = datetime(2026, 2, 12, 12, 0, 0)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO login_rate_limits (limiter_key, failed_attempts, first_failed_at, last_failed_at, locked_until)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "old-attempts",
                    1,
                    (now - timedelta(days=4)).isoformat(timespec="seconds"),
                    (now - timedelta(days=4)).isoformat(timespec="seconds"),
                    None,
                ),
            )
            conn.execute(
                """
                INSERT INTO login_rate_limits (limiter_key, failed_attempts, first_failed_at, last_failed_at, locked_until)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "expired-lock",
                    server.LOGIN_MAX_ATTEMPTS,
                    (now - timedelta(hours=2)).isoformat(timespec="seconds"),
                    (now - timedelta(hours=2)).isoformat(timespec="seconds"),
                    (now - timedelta(minutes=1)).isoformat(timespec="seconds"),
                ),
            )
            conn.execute(
                """
                INSERT INTO login_rate_limits (limiter_key, failed_attempts, first_failed_at, last_failed_at, locked_until)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "active-lock",
                    server.LOGIN_MAX_ATTEMPTS,
                    now.isoformat(timespec="seconds"),
                    now.isoformat(timespec="seconds"),
                    (now + timedelta(minutes=10)).isoformat(timespec="seconds"),
                ),
            )

            deleted = server.cleanup_login_rate_limits(conn, now=now, retention=timedelta(hours=24))
            self.assertEqual(deleted, 2)

            remaining = {
                row["limiter_key"]
                for row in conn.execute("SELECT limiter_key FROM login_rate_limits").fetchall()
            }
            self.assertEqual(remaining, {"active-lock"})

    def test_session_duration_policy(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(server.session_duration_days(), 30)

        with patch.dict("os.environ", {"ENV": "production"}, clear=True):
            self.assertEqual(server.session_duration_days(), 7)

        with patch.dict("os.environ", {"SESSION_DURATION_DAYS": "14"}, clear=True):
            self.assertEqual(server.session_duration_days(), 14)

    def test_session_idle_timeout_policy_and_expiry(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(server.session_idle_timeout_minutes(), 0)

        with patch.dict("os.environ", {"SESSION_IDLE_TIMEOUT_MINUTES": "10"}, clear=True):
            self.assertEqual(server.session_idle_timeout_minutes(), 10)
            now = datetime(2026, 2, 12, 10, 0, 0)
            active = (now - timedelta(minutes=5)).isoformat(timespec="seconds")
            stale = (now - timedelta(minutes=11)).isoformat(timespec="seconds")
            self.assertFalse(server.is_session_idle_expired(active, now=now))
            self.assertTrue(server.is_session_idle_expired(stale, now=now))

    def test_issue_session_rotates_existing_sessions_for_user(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
                ("Rotate User", "rotate@example.com", server.hash_password("password123"), server.utc_now_iso()),
            )
            user_id = conn.execute(
                "SELECT id FROM users WHERE email = ?", ("rotate@example.com",)
            ).fetchone()["id"]

            old_token = server.issue_session(conn, int(user_id))
            new_token = server.issue_session(conn, int(user_id))

            rows = conn.execute(
                "SELECT token_hash FROM sessions WHERE user_id = ?",
                (int(user_id),),
            ).fetchall()

        self.assertEqual(len(rows), 1)
        self.assertNotEqual(old_token, new_token)
        self.assertEqual(rows[0]["token_hash"], server.hash_session_token(new_token))

    def test_default_security_headers_include_required_policies(self) -> None:
        headers = dict(server.default_security_headers())
        self.assertIn("Content-Security-Policy", headers)
        self.assertIn("X-Frame-Options", headers)
        self.assertIn("X-Content-Type-Options", headers)
        self.assertIn("Referrer-Policy", headers)
        self.assertIn("Permissions-Policy", headers)

        csp = headers["Content-Security-Policy"]
        self.assertIn("default-src 'self'", csp)
        self.assertIn("script-src 'self'", csp)
        self.assertIn("frame-ancestors 'none'", csp)

    def test_hash_identifier_is_deterministic(self) -> None:
        value1 = server.hash_identifier("User@Example.com")
        value2 = server.hash_identifier(" user@example.com ")
        self.assertEqual(value1, value2)
        self.assertEqual(len(value1), 16)

    def test_build_security_event_payload(self) -> None:
        payload = server.build_security_event(
            "login_failed",
            email_hash="abc123",
            retry_after_seconds=30,
            ignored_none=None,
        )
        self.assertEqual(payload["event"], "login_failed")
        self.assertEqual(payload["email_hash"], "abc123")
        self.assertEqual(payload["retry_after_seconds"], 30)
        self.assertIn("timestamp", payload)
        self.assertNotIn("ignored_none", payload)


if __name__ == "__main__":
    unittest.main()
