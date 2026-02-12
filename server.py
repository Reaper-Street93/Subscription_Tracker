from __future__ import annotations

import calendar
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
from datetime import date, datetime, timedelta
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

DB_PATH = Path(__file__).with_name("subscriptions.db")
STATIC_DIR = Path(__file__).with_name("static")
DATE_FORMAT = "%Y-%m-%d"
SESSION_COOKIE_NAME = "subtracker_session"
CSRF_COOKIE_NAME = "subtracker_csrf"
SESSION_DURATION_DAYS = 30
PASSWORD_HASH_ITERATIONS = 200_000
LOGIN_MAX_ATTEMPTS = 5
LOGIN_ATTEMPT_WINDOW = timedelta(minutes=10)
LOGIN_LOCKOUT_DURATION = timedelta(minutes=15)

CYCLE_TO_MONTHS = {
    "monthly": 1,
    "quarterly": 3,
    "yearly": 12,
}
DEFAULT_CATEGORIES = [
    "Streaming",
    "Productivity",
    "Utilities",
    "Fitness",
    "Storage",
    "Music",
    "Education",
    "Other",
]


def utc_now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def default_security_headers() -> list[tuple[str, str]]:
    csp = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )
    return [
        ("Content-Security-Policy", csp),
        ("X-Frame-Options", "DENY"),
        ("X-Content-Type-Options", "nosniff"),
        ("Referrer-Policy", "strict-origin-when-cross-origin"),
        ("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()"),
    ]


def should_use_secure_cookie() -> bool:
    cookie_secure_env = os.environ.get("COOKIE_SECURE", "").strip().lower()
    if cookie_secure_env in {"1", "true", "yes", "on"}:
        return True
    return os.environ.get("ENV", "").strip().lower() == "production"


def cookie_samesite() -> str:
    raw = os.environ.get("COOKIE_SAMESITE", "Lax").strip().capitalize()
    if raw in {"Lax", "Strict", "None"}:
        return raw
    return "Lax"


def build_cookie_header(
    name: str,
    value: str,
    *,
    max_age: int,
    http_only: bool,
) -> str:
    parts = [
        f"{name}={value}",
        "Path=/",
        f"SameSite={cookie_samesite()}",
        f"Max-Age={max_age}",
    ]
    if http_only:
        parts.append("HttpOnly")
    if should_use_secure_cookie():
        parts.append("Secure")
    return "; ".join(parts)


def is_valid_csrf_pair(cookie_token: str | None, header_token: str | None) -> bool:
    if not cookie_token or not header_token:
        return False
    return hmac.compare_digest(cookie_token, header_token)


class LoginRateLimiter:
    def __init__(
        self,
        *,
        max_attempts: int = LOGIN_MAX_ATTEMPTS,
        attempt_window: timedelta = LOGIN_ATTEMPT_WINDOW,
        lockout_duration: timedelta = LOGIN_LOCKOUT_DURATION,
    ) -> None:
        self.max_attempts = max_attempts
        self.attempt_window = attempt_window
        self.lockout_duration = lockout_duration
        self._entries: dict[str, dict[str, object]] = {}
        self._lock = threading.Lock()

    def _prune_attempts(self, attempts: list[datetime], now: datetime) -> list[datetime]:
        return [item for item in attempts if now - item <= self.attempt_window]

    def is_limited(self, key: str, now: datetime | None = None) -> tuple[bool, int]:
        current_time = now or datetime.utcnow()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return False, 0

            locked_until = entry.get("locked_until")
            if isinstance(locked_until, datetime):
                if locked_until > current_time:
                    retry_after = int((locked_until - current_time).total_seconds())
                    return True, max(1, retry_after)
                entry["locked_until"] = None
                entry["attempts"] = []

            attempts = self._prune_attempts(list(entry.get("attempts", [])), current_time)
            entry["attempts"] = attempts
            return False, 0

    def register_failure(self, key: str, now: datetime | None = None) -> int:
        current_time = now or datetime.utcnow()
        with self._lock:
            entry = self._entries.setdefault(key, {"attempts": [], "locked_until": None})
            attempts = self._prune_attempts(list(entry.get("attempts", [])), current_time)
            attempts.append(current_time)
            entry["attempts"] = attempts

            if len(attempts) >= self.max_attempts:
                locked_until = current_time + self.lockout_duration
                entry["locked_until"] = locked_until
                return int(self.lockout_duration.total_seconds())
            return 0

    def clear(self, key: str) -> None:
        with self._lock:
            self._entries.pop(key, None)


LOGIN_RATE_LIMITER = LoginRateLimiter()


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                amount REAL NOT NULL,
                billing_cycle TEXT NOT NULL,
                next_payment_date TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL COLLATE NOCASE,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, name),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        ensure_subscription_user_column(conn)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_token_hash ON sessions(token_hash)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_user_id ON subscriptions(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_categories_user_id ON categories(user_id)")


def ensure_subscription_user_column(conn: sqlite3.Connection) -> None:
    columns = conn.execute("PRAGMA table_info(subscriptions)").fetchall()
    column_names = {column[1] for column in columns}
    if "user_id" not in column_names:
        conn.execute("ALTER TABLE subscriptions ADD COLUMN user_id INTEGER")


def add_months(source_date: date, months: int) -> date:
    month_index = source_date.month - 1 + months
    target_year = source_date.year + month_index // 12
    target_month = month_index % 12 + 1
    max_day = calendar.monthrange(target_year, target_month)[1]
    return source_date.replace(year=target_year, month=target_month, day=min(source_date.day, max_day))


def parse_date(value: str) -> date:
    return datetime.strptime(value, DATE_FORMAT).date()


def monthly_cost(amount: float, billing_cycle: str) -> float:
    cycle_months = CYCLE_TO_MONTHS[billing_cycle]
    return round(amount / cycle_months, 2)


def next_due_date(initial_date: date, billing_cycle: str, today: date | None = None) -> date:
    today = today or date.today()
    current_due = initial_date
    months = CYCLE_TO_MONTHS[billing_cycle]

    while current_due < today:
        current_due = add_months(current_due, months)

    return current_due


def hash_password(password: str, salt: bytes | None = None) -> str:
    if salt is None:
        salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_HASH_ITERATIONS)
    return f"{salt.hex()}:{digest.hex()}"


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        salt_hex, digest_hex = encoded_hash.split(":", maxsplit=1)
    except ValueError:
        return False

    salt = bytes.fromhex(salt_hex)
    expected = bytes.fromhex(digest_hex)
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_HASH_ITERATIONS)
    return hmac.compare_digest(candidate, expected)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def serialize_user(row: sqlite3.Row) -> dict[str, object]:
    return {
        "id": row["id"],
        "name": row["name"],
        "email": row["email"],
    }


def serialize_subscription(row: sqlite3.Row, today: date | None = None) -> dict[str, object]:
    today = today or date.today()
    initial_due = parse_date(row["next_payment_date"])
    due_date = next_due_date(initial_due, row["billing_cycle"], today=today)

    return {
        "id": row["id"],
        "name": row["name"],
        "category": row["category"],
        "amount": round(float(row["amount"]), 2),
        "billingCycle": row["billing_cycle"],
        "initialPaymentDate": row["next_payment_date"],
        "nextPaymentDate": due_date.strftime(DATE_FORMAT),
        "daysUntilPayment": (due_date - today).days,
        "monthlyCost": monthly_cost(float(row["amount"]), row["billing_cycle"]),
    }


def normalize_category_name(value: str) -> str:
    cleaned = " ".join(value.split()).strip()
    return cleaned if cleaned else "Other"


def parse_subscription_payload(body: dict[str, object]) -> tuple[dict[str, object] | None, str | None]:
    name = str(body.get("name", "")).strip()
    category = normalize_category_name(str(body.get("category", "Other")))
    billing_cycle = str(body.get("billingCycle", "")).strip().lower()
    payment_date = str(body.get("nextPaymentDate", "")).strip()

    try:
        amount = float(body.get("amount", 0))
    except (TypeError, ValueError):
        return None, "Amount must be a number"

    if not name:
        return None, "Subscription name is required"
    if amount <= 0:
        return None, "Amount must be greater than 0"
    if billing_cycle not in CYCLE_TO_MONTHS:
        return None, "Billing cycle must be monthly, quarterly, or yearly"

    try:
        parse_date(payment_date)
    except ValueError:
        return None, "nextPaymentDate must be YYYY-MM-DD"

    return (
        {
            "name": name,
            "category": category,
            "amount": amount,
            "billing_cycle": billing_cycle,
            "payment_date": payment_date,
        },
        None,
    )


def parse_auth_payload(body: dict[str, object], require_name: bool) -> tuple[dict[str, str] | None, str | None]:
    name = str(body.get("name", "")).strip()
    email = str(body.get("email", "")).strip().lower()
    password = str(body.get("password", ""))

    if require_name and len(name) < 2:
        return None, "Name must be at least 2 characters"
    if "@" not in email or "." not in email:
        return None, "A valid email is required"
    if len(password) < 8:
        return None, "Password must be at least 8 characters"

    if not require_name and not name:
        name = ""

    return {"name": name, "email": email, "password": password}, None


def issue_session(conn: sqlite3.Connection, user_id: int) -> str:
    conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (utc_now_iso(),))
    token = secrets.token_urlsafe(32)
    token_hash = hash_session_token(token)
    expires_at = (datetime.utcnow() + timedelta(days=SESSION_DURATION_DAYS)).isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO sessions (user_id, token_hash, expires_at, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (user_id, token_hash, expires_at, utc_now_iso()),
    )
    return token


def seed_default_categories(conn: sqlite3.Connection, user_id: int) -> None:
    created_at = utc_now_iso()
    for category in DEFAULT_CATEGORIES:
        conn.execute(
            """
            INSERT OR IGNORE INTO categories (user_id, name, created_at)
            VALUES (?, ?, ?)
            """,
            (user_id, normalize_category_name(category), created_at),
        )


def ensure_category_exists(conn: sqlite3.Connection, user_id: int, category: str) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO categories (user_id, name, created_at)
        VALUES (?, ?, ?)
        """,
        (user_id, normalize_category_name(category), utc_now_iso()),
    )


class SubscriptionHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def end_headers(self) -> None:
        # Apply baseline browser security headers for both API and static responses.
        for key, value in default_security_headers():
            self.send_header(key, value)
        super().end_headers()

    def _send_json(
        self,
        payload: dict[str, object],
        status: int = 200,
        extra_headers: list[tuple[str, str]] | None = None,
    ) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if extra_headers:
            for key, value in extra_headers:
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, object]:
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            return {}

        raw = self.rfile.read(content_length)
        if not raw:
            return {}

        return json.loads(raw.decode("utf-8"))

    def _db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _session_token_from_cookie(self) -> str | None:
        cookie_header = self.headers.get("Cookie")
        if not cookie_header:
            return None

        cookie = SimpleCookie()
        cookie.load(cookie_header)
        morsel = cookie.get(SESSION_COOKIE_NAME)
        return morsel.value if morsel else None

    def _csrf_token_from_cookie(self) -> str | None:
        cookie_header = self.headers.get("Cookie")
        if not cookie_header:
            return None

        cookie = SimpleCookie()
        cookie.load(cookie_header)
        morsel = cookie.get(CSRF_COOKIE_NAME)
        return morsel.value if morsel else None

    def _csrf_token_from_header(self) -> str | None:
        return self.headers.get("X-CSRF-Token")

    def _csrf_is_valid(self) -> bool:
        return is_valid_csrf_pair(self._csrf_token_from_cookie(), self._csrf_token_from_header())

    def _require_csrf(self) -> bool:
        if self._csrf_is_valid():
            return True
        self._send_json({"error": "Invalid CSRF token"}, status=403)
        return False

    def _client_ip(self) -> str:
        forwarded_for = self.headers.get("X-Forwarded-For", "").strip()
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        return self.client_address[0] if self.client_address else "unknown"

    def _current_user(self) -> sqlite3.Row | None:
        token = self._session_token_from_cookie()
        if not token:
            return None

        token_hash = hash_session_token(token)
        now = utc_now_iso()
        with self._db() as conn:
            row = conn.execute(
                """
                SELECT users.*
                FROM sessions
                JOIN users ON users.id = sessions.user_id
                WHERE sessions.token_hash = ? AND sessions.expires_at > ?
                """,
                (token_hash, now),
            ).fetchone()
        return row

    def _require_auth_user(self) -> sqlite3.Row | None:
        user = self._current_user()
        if user is None:
            self._send_json({"error": "Authentication required"}, status=401)
            return None
        return user

    def _session_cookie_header(self, token: str) -> tuple[str, str]:
        max_age = SESSION_DURATION_DAYS * 24 * 60 * 60
        return (
            "Set-Cookie",
            build_cookie_header(SESSION_COOKIE_NAME, token, max_age=max_age, http_only=True),
        )

    def _clear_session_cookie_header(self) -> tuple[str, str]:
        return (
            "Set-Cookie",
            build_cookie_header(SESSION_COOKIE_NAME, "", max_age=0, http_only=True),
        )

    def _csrf_cookie_header(self, token: str) -> tuple[str, str]:
        max_age = SESSION_DURATION_DAYS * 24 * 60 * 60
        return (
            "Set-Cookie",
            build_cookie_header(CSRF_COOKIE_NAME, token, max_age=max_age, http_only=False),
        )

    def _clear_csrf_cookie_header(self) -> tuple[str, str]:
        return (
            "Set-Cookie",
            build_cookie_header(CSRF_COOKIE_NAME, "", max_age=0, http_only=False),
        )

    def do_GET(self) -> None:
        parsed = urlparse(self.path)

        if parsed.path == "/api/subscriptions":
            return self._get_subscriptions()
        if parsed.path == "/api/reminders":
            return self._get_reminders()
        if parsed.path == "/api/categories":
            return self._get_categories()
        if parsed.path == "/api/auth/me":
            return self._get_auth_me()
        if parsed.path == "/api/health":
            return self._send_json({"ok": True})

        if parsed.path == "/":
            self.path = "/index.html"

        return super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/subscriptions":
            return self._create_subscription()
        if parsed.path == "/api/categories":
            return self._create_category()
        if parsed.path == "/api/auth/signup":
            return self._auth_signup()
        if parsed.path == "/api/auth/login":
            return self._auth_login()
        if parsed.path == "/api/auth/logout":
            return self._auth_logout()

        return self._send_json({"error": "Not found"}, status=404)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        path_parts = parsed.path.strip("/").split("/")

        if len(path_parts) == 3 and path_parts[0] == "api" and path_parts[1] == "subscriptions":
            try:
                sub_id = int(path_parts[2])
            except ValueError:
                return self._send_json({"error": "Invalid subscription id"}, status=400)
            return self._delete_subscription(sub_id)
        if len(path_parts) == 3 and path_parts[0] == "api" and path_parts[1] == "categories":
            try:
                category_id = int(path_parts[2])
            except ValueError:
                return self._send_json({"error": "Invalid category id"}, status=400)
            return self._delete_category(category_id)

        return self._send_json({"error": "Not found"}, status=404)

    def do_PUT(self) -> None:
        parsed = urlparse(self.path)
        path_parts = parsed.path.strip("/").split("/")

        if len(path_parts) == 3 and path_parts[0] == "api" and path_parts[1] == "subscriptions":
            try:
                sub_id = int(path_parts[2])
            except ValueError:
                return self._send_json({"error": "Invalid subscription id"}, status=400)
            return self._update_subscription(sub_id)

        return self._send_json({"error": "Not found"}, status=404)

    def _get_auth_me(self) -> None:
        user = self._current_user()
        if user is None:
            return self._send_json({"user": None})
        extra_headers: list[tuple[str, str]] = []
        if not self._csrf_token_from_cookie():
            extra_headers.append(self._csrf_cookie_header(secrets.token_urlsafe(24)))
        self._send_json({"user": serialize_user(user)}, extra_headers=extra_headers or None)

    def _auth_signup(self) -> None:
        try:
            body = self._read_json()
        except json.JSONDecodeError:
            return self._send_json({"error": "Invalid JSON body"}, status=400)

        payload, error = parse_auth_payload(body, require_name=True)
        if error or payload is None:
            return self._send_json({"error": error or "Invalid payload"}, status=400)

        password_hash = hash_password(payload["password"])
        created_at = utc_now_iso()

        try:
            with self._db() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO users (name, email, password_hash, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (payload["name"], payload["email"], password_hash, created_at),
                )
                user_id = int(cursor.lastrowid)
                token = issue_session(conn, user_id)
                user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
                seed_default_categories(conn, user_id)
        except sqlite3.IntegrityError:
            return self._send_json({"error": "An account with that email already exists"}, status=409)

        if user is None:
            return self._send_json({"error": "Unable to create account"}, status=500)

        csrf_token = secrets.token_urlsafe(24)
        self._send_json(
            {"user": serialize_user(user)},
            status=201,
            extra_headers=[self._session_cookie_header(token), self._csrf_cookie_header(csrf_token)],
        )

    def _auth_login(self) -> None:
        try:
            body = self._read_json()
        except json.JSONDecodeError:
            return self._send_json({"error": "Invalid JSON body"}, status=400)

        payload, error = parse_auth_payload(body, require_name=False)
        if error or payload is None:
            return self._send_json({"error": error or "Invalid payload"}, status=400)

        limit_key = f"{self._client_ip()}|{payload['email']}"
        limited, retry_after = LOGIN_RATE_LIMITER.is_limited(limit_key)
        if limited:
            return self._send_json(
                {"error": "Too many login attempts. Try again later."},
                status=429,
                extra_headers=[("Retry-After", str(retry_after))],
            )

        with self._db() as conn:
            user = conn.execute("SELECT * FROM users WHERE email = ?", (payload["email"],)).fetchone()
            if user is None or not verify_password(payload["password"], str(user["password_hash"])):
                lock_seconds = LOGIN_RATE_LIMITER.register_failure(limit_key)
                if lock_seconds > 0:
                    return self._send_json(
                        {"error": "Too many login attempts. Try again later."},
                        status=429,
                        extra_headers=[("Retry-After", str(lock_seconds))],
                    )
                return self._send_json({"error": "Invalid email or password"}, status=401)

            seed_default_categories(conn, int(user["id"]))
            token = issue_session(conn, int(user["id"]))
            LOGIN_RATE_LIMITER.clear(limit_key)

        csrf_token = secrets.token_urlsafe(24)
        self._send_json(
            {"user": serialize_user(user)},
            extra_headers=[self._session_cookie_header(token), self._csrf_cookie_header(csrf_token)],
        )

    def _auth_logout(self) -> None:
        token = self._session_token_from_cookie()
        if token and not self._require_csrf():
            return

        if token:
            token_hash = hash_session_token(token)
            with self._db() as conn:
                conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))

        self._send_json(
            {"loggedOut": True},
            extra_headers=[self._clear_session_cookie_header(), self._clear_csrf_cookie_header()],
        )

    def _get_subscriptions(self) -> None:
        user = self._require_auth_user()
        if user is None:
            return

        today = date.today()
        with self._db() as conn:
            rows = conn.execute(
                "SELECT * FROM subscriptions WHERE user_id = ? ORDER BY created_at DESC",
                (int(user["id"]),),
            ).fetchall()

        subscriptions = [serialize_subscription(row, today=today) for row in rows]
        total_monthly = round(sum(float(item["monthlyCost"]) for item in subscriptions), 2)

        by_category: dict[str, float] = {}
        for item in subscriptions:
            by_category[item["category"]] = round(
                by_category.get(item["category"], 0.0) + float(item["monthlyCost"]),
                2,
            )

        spending_by_category = [
            {"category": category, "monthlyCost": amount}
            for category, amount in sorted(by_category.items(), key=lambda pair: pair[1], reverse=True)
        ]

        self._send_json(
            {
                "subscriptions": subscriptions,
                "totalMonthlySpend": total_monthly,
                "spendingByCategory": spending_by_category,
            }
        )

    def _get_categories(self) -> None:
        user = self._require_auth_user()
        if user is None:
            return

        with self._db() as conn:
            rows = conn.execute(
                "SELECT id, name FROM categories WHERE user_id = ? ORDER BY name COLLATE NOCASE ASC",
                (int(user["id"]),),
            ).fetchall()

        categories = [{"id": row["id"], "name": row["name"]} for row in rows]
        self._send_json({"categories": categories})

    def _get_reminders(self) -> None:
        user = self._require_auth_user()
        if user is None:
            return

        today = date.today()
        with self._db() as conn:
            rows = conn.execute(
                "SELECT * FROM subscriptions WHERE user_id = ? ORDER BY created_at DESC",
                (int(user["id"]),),
            ).fetchall()

        reminders = []
        for row in rows:
            item = serialize_subscription(row, today=today)
            reminders.append(
                {
                    "id": item["id"],
                    "name": item["name"],
                    "nextPaymentDate": item["nextPaymentDate"],
                    "daysUntilPayment": item["daysUntilPayment"],
                    "amount": item["amount"],
                    "billingCycle": item["billingCycle"],
                    "isDueSoon": int(item["daysUntilPayment"]) <= 7,
                }
            )

        reminders.sort(key=lambda entry: (entry["daysUntilPayment"], entry["name"]))

        self._send_json(
            {
                "reminders": reminders,
                "nextReminder": reminders[0] if reminders else None,
            }
        )

    def _create_subscription(self) -> None:
        user = self._require_auth_user()
        if user is None:
            return
        if not self._require_csrf():
            return

        try:
            body = self._read_json()
        except json.JSONDecodeError:
            return self._send_json({"error": "Invalid JSON body"}, status=400)

        payload, error = parse_subscription_payload(body)
        if error:
            return self._send_json({"error": error}, status=400)
        if payload is None:
            return self._send_json({"error": "Invalid payload"}, status=400)

        created_at = utc_now_iso()
        with self._db() as conn:
            ensure_category_exists(conn, int(user["id"]), str(payload["category"]))
            cursor = conn.execute(
                """
                INSERT INTO subscriptions (user_id, name, category, amount, billing_cycle, next_payment_date, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(user["id"]),
                    payload["name"],
                    payload["category"],
                    payload["amount"],
                    payload["billing_cycle"],
                    payload["payment_date"],
                    created_at,
                ),
            )
            new_id = cursor.lastrowid
            row = conn.execute(
                "SELECT * FROM subscriptions WHERE id = ? AND user_id = ?",
                (new_id, int(user["id"])),
            ).fetchone()

        if row is None:
            return self._send_json({"error": "Unable to create subscription"}, status=500)

        self._send_json({"subscription": serialize_subscription(row)}, status=201)

    def _update_subscription(self, sub_id: int) -> None:
        user = self._require_auth_user()
        if user is None:
            return
        if not self._require_csrf():
            return

        try:
            body = self._read_json()
        except json.JSONDecodeError:
            return self._send_json({"error": "Invalid JSON body"}, status=400)

        payload, error = parse_subscription_payload(body)
        if error:
            return self._send_json({"error": error}, status=400)
        if payload is None:
            return self._send_json({"error": "Invalid payload"}, status=400)

        with self._db() as conn:
            ensure_category_exists(conn, int(user["id"]), str(payload["category"]))
            cursor = conn.execute(
                """
                UPDATE subscriptions
                SET name = ?, category = ?, amount = ?, billing_cycle = ?, next_payment_date = ?
                WHERE id = ? AND user_id = ?
                """,
                (
                    payload["name"],
                    payload["category"],
                    payload["amount"],
                    payload["billing_cycle"],
                    payload["payment_date"],
                    sub_id,
                    int(user["id"]),
                ),
            )
            if cursor.rowcount == 0:
                return self._send_json({"error": "Subscription not found"}, status=404)

            row = conn.execute(
                "SELECT * FROM subscriptions WHERE id = ? AND user_id = ?",
                (sub_id, int(user["id"])),
            ).fetchone()

        if row is None:
            return self._send_json({"error": "Subscription not found"}, status=404)

        self._send_json({"subscription": serialize_subscription(row)})

    def _delete_subscription(self, sub_id: int) -> None:
        user = self._require_auth_user()
        if user is None:
            return
        if not self._require_csrf():
            return

        with self._db() as conn:
            cursor = conn.execute(
                "DELETE FROM subscriptions WHERE id = ? AND user_id = ?",
                (sub_id, int(user["id"])),
            )

        if cursor.rowcount == 0:
            return self._send_json({"error": "Subscription not found"}, status=404)

        self._send_json({"deleted": True})

    def _create_category(self) -> None:
        user = self._require_auth_user()
        if user is None:
            return
        if not self._require_csrf():
            return

        try:
            body = self._read_json()
        except json.JSONDecodeError:
            return self._send_json({"error": "Invalid JSON body"}, status=400)

        name = normalize_category_name(str(body.get("name", "")))
        if len(name) < 2:
            return self._send_json({"error": "Category name must be at least 2 characters"}, status=400)
        if len(name) > 40:
            return self._send_json({"error": "Category name must be 40 characters or fewer"}, status=400)

        try:
            with self._db() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO categories (user_id, name, created_at)
                    VALUES (?, ?, ?)
                    """,
                    (int(user["id"]), name, utc_now_iso()),
                )
                category_id = int(cursor.lastrowid)
                row = conn.execute(
                    "SELECT id, name FROM categories WHERE id = ? AND user_id = ?",
                    (category_id, int(user["id"])),
                ).fetchone()
        except sqlite3.IntegrityError:
            return self._send_json({"error": "That category already exists"}, status=409)

        if row is None:
            return self._send_json({"error": "Unable to create category"}, status=500)

        self._send_json({"category": {"id": row["id"], "name": row["name"]}}, status=201)

    def _delete_category(self, category_id: int) -> None:
        user = self._require_auth_user()
        if user is None:
            return
        if not self._require_csrf():
            return

        with self._db() as conn:
            category_row = conn.execute(
                "SELECT id, name FROM categories WHERE id = ? AND user_id = ?",
                (category_id, int(user["id"])),
            ).fetchone()
            if category_row is None:
                return self._send_json({"error": "Category not found"}, status=404)

            usage_row = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM subscriptions
                WHERE user_id = ? AND category = ? COLLATE NOCASE
                """,
                (int(user["id"]), str(category_row["name"])),
            ).fetchone()
            usage_count = int(usage_row["count"]) if usage_row else 0
            if usage_count > 0:
                return self._send_json(
                    {"error": "Cannot delete a category that is in use by subscriptions"},
                    status=409,
                )

            conn.execute(
                "DELETE FROM categories WHERE id = ? AND user_id = ?",
                (category_id, int(user["id"])),
            )

        self._send_json({"deleted": True})


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "127.0.0.1")

    server = ThreadingHTTPServer((host, port), SubscriptionHandler)
    print(f"Subscription tracker running at http://{host}:{port}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
