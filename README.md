# Wearstack

Clothing retail management system (GST billing, inventory, offline-first POS) for independent
Indian clothing shops. See `datahouse/wearstack_project_brief.md` and `datahouse/plan.md`.

## Layout
- `backend/` FastAPI + SQLAlchemy 2.0 + Alembic (managed with `uv`)
- `frontend/` React + TypeScript + Vite + Tailwind
- `docs/` documentation, `datahouse/` brief and plan

## Run with Docker
    cp .env.example .env
    docker compose up --build
API: http://localhost:8010/health · Web: http://localhost:5173
Host ports default to 8010 (API), 5434 (Postgres), 5173 (web); override via `BACKEND_PORT`, `DB_PORT`,
`FRONTEND_PORT` in `.env`.

On first visit, open the web app: it redirects to `/setup` to create the business, first store and
owner account. Migrations run automatically when the backend container starts.

## Run locally
    docker compose up db -d
    cd backend && uv sync && uv run uvicorn app.main:app --reload --port 8010
    cd frontend && npm install && npm run dev

## Checks
    cd backend && uv run ruff check . && uv run mypy app && uv run pytest   # needs `docker compose up db -d`
    cd frontend && npm run lint && npm run format:check && npm run typecheck && npm run build

## Adding UI components
    cd frontend && npx shadcn@latest add <component>

## Demo data
On an **empty development database** only:

    docker compose exec backend uv run python -m app.seed_demo

Creates a demo shop (two stores, 8 products, ~170 sales over 45 days) so you can explore reports.
Log in as `owner@example.com`, `manager@example.com` or `cashier@example.com` /
`demo-password-123`. It refuses to run outside development or if any business exists. Its GST
rates are labelled DEMO and are not real rates.

## End-to-end tests
A real browser drives the running stack through a shop's first day (needs an empty database):

    docker compose down -v && docker compose up -d --build
    cd e2e && npm ci && npx playwright install chromium && npm test

Set `BASE_URL` to run it against another deployment, e.g. the production stack.

## Production
See [docs/operations.md](docs/operations.md): deployment, nightly backups, restore, updating.

