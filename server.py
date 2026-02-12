from __future__ import annotations

import calendar
import json
import os
import sqlite3
from datetime import date, datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

DB_PATH = Path(__file__).with_name("subscriptions.db")
STATIC_DIR = Path(__file__).with_name("static")
DATE_FORMAT = "%Y-%m-%d"
CYCLE_TO_MONTHS = {
    "monthly": 1,
    "quarterly": 3,
    "yearly": 12,
}


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                amount REAL NOT NULL,
                billing_cycle TEXT NOT NULL,
                next_payment_date TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )


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


def parse_subscription_payload(body: dict[str, object]) -> tuple[dict[str, object] | None, str | None]:
    name = str(body.get("name", "")).strip()
    category = str(body.get("category", "Other")).strip() or "Other"
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


class SubscriptionHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def _send_json(self, payload: dict[str, object], status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
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
        return conn

    def do_GET(self) -> None:
        parsed = urlparse(self.path)

        if parsed.path == "/api/subscriptions":
            return self._get_subscriptions()
        if parsed.path == "/api/reminders":
            return self._get_reminders()
        if parsed.path == "/api/health":
            return self._send_json({"ok": True})

        if parsed.path == "/":
            self.path = "/index.html"

        return super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/subscriptions":
            return self._create_subscription()

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

    def _get_subscriptions(self) -> None:
        today = date.today()
        with self._db() as conn:
            rows = conn.execute("SELECT * FROM subscriptions ORDER BY created_at DESC").fetchall()

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

    def _get_reminders(self) -> None:
        today = date.today()
        with self._db() as conn:
            rows = conn.execute("SELECT * FROM subscriptions ORDER BY created_at DESC").fetchall()

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
        try:
            body = self._read_json()
        except json.JSONDecodeError:
            return self._send_json({"error": "Invalid JSON body"}, status=400)

        payload, error = parse_subscription_payload(body)
        if error:
            return self._send_json({"error": error}, status=400)
        if payload is None:
            return self._send_json({"error": "Invalid payload"}, status=400)

        created_at = datetime.utcnow().isoformat(timespec="seconds")
        with self._db() as conn:
            cursor = conn.execute(
                """
                INSERT INTO subscriptions (name, category, amount, billing_cycle, next_payment_date, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["name"],
                    payload["category"],
                    payload["amount"],
                    payload["billing_cycle"],
                    payload["payment_date"],
                    created_at,
                ),
            )
            new_id = cursor.lastrowid
            row = conn.execute("SELECT * FROM subscriptions WHERE id = ?", (new_id,)).fetchone()

        if row is None:
            return self._send_json({"error": "Unable to create subscription"}, status=500)

        self._send_json({"subscription": serialize_subscription(row)}, status=201)

    def _update_subscription(self, sub_id: int) -> None:
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
            cursor = conn.execute(
                """
                UPDATE subscriptions
                SET name = ?, category = ?, amount = ?, billing_cycle = ?, next_payment_date = ?
                WHERE id = ?
                """,
                (
                    payload["name"],
                    payload["category"],
                    payload["amount"],
                    payload["billing_cycle"],
                    payload["payment_date"],
                    sub_id,
                ),
            )
            if cursor.rowcount == 0:
                return self._send_json({"error": "Subscription not found"}, status=404)

            row = conn.execute("SELECT * FROM subscriptions WHERE id = ?", (sub_id,)).fetchone()

        if row is None:
            return self._send_json({"error": "Subscription not found"}, status=404)

        self._send_json({"subscription": serialize_subscription(row)})

    def _delete_subscription(self, sub_id: int) -> None:
        with self._db() as conn:
            cursor = conn.execute("DELETE FROM subscriptions WHERE id = ?", (sub_id,))

        if cursor.rowcount == 0:
            return self._send_json({"error": "Subscription not found"}, status=404)

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
