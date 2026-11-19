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
