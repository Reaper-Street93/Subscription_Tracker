# Subscription Compass

A full-stack subscription tracker built with a Python backend and a vanilla HTML/CSS/JS frontend.

## Features
- User authentication (sign up, sign in, sign out)
- Add subscription
- Edit subscription
- Search, filter, and sort subscriptions
- Category management (create/delete categories)
- Monthly cost auto-calculated (monthly, quarterly, yearly billing)
- Total monthly spend summary
- Upcoming payment reminders
- Optional browser notifications for payments due in 3 days or less
- Pie chart of monthly spend by category

## Tech Stack
- Backend: Python standard library (`http.server`, `sqlite3`)
- Database: SQLite (`subscriptions.db`)
- Frontend: Vanilla HTML, CSS, JavaScript

## Project Structure
- `server.py`: API server, SQLite schema, cost/reminder calculation logic
- `static/index.html`: App layout and dashboard structure
- `static/styles.css`: Visual design, responsive layout, motion, and theme
- `static/app.js`: API integration and dynamic rendering

## Run Locally
1. Use Python 3.9+.
2. From project root, run:
   ```bash
   /usr/bin/python3 server.py
   ```
3. Open [http://127.0.0.1:8000](http://127.0.0.1:8000)

## Run Tests
From project root:
```bash
/usr/bin/python3 -m unittest discover -s tests -v
```

## Run With Docker
1. Build:
   ```bash
   docker build -t subscription-compass .
   ```
2. Run:
   ```bash
   docker run --rm -p 8000:8000 subscription-compass
   ```
3. Open [http://127.0.0.1:8000](http://127.0.0.1:8000)

## Deploy (Generic Python Host)
- Build command: none required
- Start command:
  ```bash
  python server.py
  ```
- Required env vars:
  - `HOST=0.0.0.0`
  - `PORT` from your provider (or `8000`)
- Recommended security env vars:
  - `ENV=production`
  - `COOKIE_SECURE=1`
  - `COOKIE_SAMESITE=Lax` (or `Strict`)
  - `SESSION_DURATION_DAYS=7`
  - `SESSION_IDLE_TIMEOUT_MINUTES=30` (set `0` to disable idle timeout)
  - `LOGIN_RATE_LIMIT_RETENTION_HOURS=48`

## Security
- Passwords are stored using PBKDF2-HMAC-SHA256 with per-user salts.
- Session auth uses `HttpOnly` cookies.
- CSRF protection is enforced on authenticated mutating routes (`POST`, `PUT`, `DELETE` for subscriptions/categories and logout) using an `X-CSRF-Token` header that must match the CSRF cookie.
- Login rate limiting is enforced per `IP + email` and persisted in SQLite (`5` attempts per `10` minutes, then `15` minute lockout).
- Stale login rate-limit rows are automatically purged (default retention `48` hours).
- HTTP security headers are applied to all responses: `Content-Security-Policy`, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, and `Permissions-Policy`.
- Sessions are rotated on login (prior sessions for the same user are invalidated).
- Session duration defaults to `30` days in local/dev and `7` days in production (override with `SESSION_DURATION_DAYS`).
- Optional session idle timeout can be enforced via `SESSION_IDLE_TIMEOUT_MINUTES`.

## API Endpoints
- `GET /api/health`
- `GET /api/auth/me`
- `POST /api/auth/signup`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/subscriptions`
- `POST /api/subscriptions`
- `PUT /api/subscriptions/:id`
- `DELETE /api/subscriptions/:id`
- `GET /api/reminders`
- `GET /api/categories`
- `POST /api/categories`
- `DELETE /api/categories/:id`

## Data Model
Each user stores:
- `name`
- `email`
- `password_hash`
- `created_at`

Each session stores:
- `user_id`
- `token_hash`
- `expires_at`
- `created_at`

Each subscription stores:
- `user_id`
- `name`
- `category`
- `amount`
- `billing_cycle` (`monthly`, `quarterly`, `yearly`)
- `next_payment_date`
- `created_at`

Each category stores:
- `user_id`
- `name`
- `created_at`

Each login rate-limit entry stores:
- `limiter_key` (`IP + email`)
- `failed_attempts`
- `first_failed_at`
- `last_failed_at`
- `locked_until`

## Calculation Rules
- Monthly cost:
  - `monthly`: `amount / 1`
  - `quarterly`: `amount / 3`
  - `yearly`: `amount / 12`
- Next payment date is rolled forward by billing cycle months until it is today or later.
