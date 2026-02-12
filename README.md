# Subscription Compass

A full-stack subscription tracker built with a Python backend and a vanilla HTML/CSS/JS frontend.

## Features
- Add subscription
- Edit subscription
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

## API Endpoints
- `GET /api/health`
- `GET /api/subscriptions`
- `POST /api/subscriptions`
- `PUT /api/subscriptions/:id`
- `DELETE /api/subscriptions/:id`
- `GET /api/reminders`

## Data Model
Each subscription stores:
- `name`
- `category`
- `amount`
- `billing_cycle` (`monthly`, `quarterly`, `yearly`)
- `next_payment_date`
- `created_at`

## Calculation Rules
- Monthly cost:
  - `monthly`: `amount / 1`
  - `quarterly`: `amount / 3`
  - `yearly`: `amount / 12`
- Next payment date is rolled forward by billing cycle months until it is today or later.
