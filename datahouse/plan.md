# Wearstack — Implementation Plan

Derived from `wearstack_project_brief.md`. Status: **draft for review**.

## 1. Guiding Constraints

- Single business, multi-store-capable data model (all tables scoped by `business_id` / `store_id`).
- Modular monolith: FastAPI + SQLAlchemy 2.0 + PostgreSQL; React + TS + Vite frontend (PWA).
- `NUMERIC` for all money; UUID PKs; immutable finalised invoices with line-item snapshots.
- Stock changes only via the `stock_movements` ledger, updated in the same DB transaction as the balance.
- Offline-ready from day one (client UUIDs, idempotency keys), even though offline ships in Release 2.
- Out of scope: alteration management, microservices, AI features, complex integrations.

## 2. Open Decisions (resolve before the relevant phase)

| # | Decision | Needed by | Options / recommendation |
|---|----------|-----------|--------------------------|
| D1 | Offline invoice numbering | Phase 1 schema | **RESOLVED:** offline receipts are provisional; server assigns final GST number on sync. Alternative: per-device pre-allocated series (needs compliance validation). |
| D2 | Offline overselling policy | Phase 5 | **RESOLVED:** a till never sells more than the stock it knows about (cached stock minus its own unsent sales); warn after 24 h without a catalogue refresh, stop after 72 h. A shortfall found at sync becomes a conflict a manager accepts (visible, reasoned stock correction; never negative) or rejects. |
| D3 | UPI/card handling | Phase 3 | Manual cashier confirmation (initial) vs. gateway integration (later). |
| D4 | Celery/Redis/S3 in Release 1 | Phase 0 | **RESOLVED:** defer. Synchronous reports, local/optional image storage first. |
| D5 | Repo layout | Phase 0 | **RESOLVED:** monorepo — `backend/`, `frontend/`, `docs/`, `datahouse/`. |
| D6 | GST rules source | Phase 3 | Confirm current HSN/rate/place-of-supply rules with a GST professional before finalising. |

## 3. Phases

### Phase 0 — Project Setup
- Repo structure, Docker Compose (Postgres, backend, frontend), `.env` handling.
- Backend skeleton: app factory, config, DB session, Alembic, health check, logging.
- Frontend skeleton: Vite, Tailwind, shadcn/ui, React Router, TanStack Query, Zustand.
- Tooling: ruff, mypy, pytest, eslint, prettier, pre-commit; GitHub Actions CI (lint + test).
- **Exit:** `docker compose up` runs both apps; CI green.

### Phase 1 — Core Schema, Auth, Business Setup
- Migrations: `businesses`, `stores`, `users`, `roles`, `permissions`, `role_permissions`, `user_store_access`, `audit_logs`, `devices`.
- Auth (JWT + refresh), password hashing, RBAC dependency, store-scoped access.
- Business/store setup endpoints and onboarding UI.
- Audit-log helper used by all later modules.
- **Exit:** owner can log in, create store/users/roles; permissions enforced by tests.

### Phase 2 — Catalogue & Inventory
- `categories`, `brands`, `products`, `product_variants`, `product_images`, `tax_rates` (effective-dated).
- SKU + barcode generation (python-barcode), HSN and GST rate per product.
- `inventory` + `stock_movements` ledger; service enforcing atomic movement + balance update.
- Opening stock, manual adjustments (with reason), movement history view.
- **Exit:** products with size/colour variants, scannable barcodes, auditable stock.

### Phase 3 — Purchases, POS Billing, Payments, Invoices
- `suppliers`, `purchases`, `purchase_items`; goods receipt increases stock via ledger.
- `customers` (basic), `sales`, `sale_items` (snapshot fields), `payments`, `invoice_sequences`, `gst_documents`.
- POS UI: barcode scan/search, cart (Zustand), discounts, customer attach, split payments (cash/UPI/card).
- GST engine: effective-dated rates, intra/inter-state split (CGST/SGST vs IGST), rounding rules.
- Invoice finalisation (transactional, gap-free numbering) + PDF via ReportLab.
- **Exit:** a complete sale produces a valid GST invoice PDF and decrements stock.

### Phase 4 — Basic Reports → **Release 1**
- Daily/weekly/monthly sales, stock on hand, low stock, purchase summary.
- CSV/PDF export. Synchronous queries; add indexes as needed.
- Hardening: E2E Playwright suite for the billing flow, seed data, deployment config.
- **Exit:** Release 1 usable in a real shop for billing + inventory.

### Phase 5 — Offline POS & Sync (Release 2) — BUILT
- Dexie schema: catalogue cache, barcode index, pending sales queue.
- Service worker/PWA install, offline detection, provisional receipts (D1).
- `sync_operations` + idempotent sync endpoint keyed by `device_id` + client transaction ID.
- Conflict detection/reporting (D2); sync status screen (pending / success / failed / conflict).
- **Exit:** sales made offline sync exactly once; stock conflicts surfaced, not overwritten.

### Phase 6 — Returns, Exchanges, Cash Register (Release 2)
- `sale_returns`, `return_items`, `refunds`; credit notes via `gst_documents`.
- Look up original invoice, partial returns, size/colour exchange, price-difference settlement.
- Return reasons; stock restored through ledger movements.
- `cash_registers`, `cash_register_entries`: open/close, expected vs. counted, variance.
- Customer purchase history view.
- **Exit:** originals untouched; every return/exchange traceable and stock-correct.

### Phase 7 — Intelligence & Retention (Later)
- Stock ageing, dead stock, size/colour analytics, reorder suggestions from sales velocity.
- Margin reporting (cost + discounts + returns + `expenses`).
- Customer segmentation, loyalty points, WhatsApp campaigns with consent tracking.
- Introduce Celery + Redis here if report load requires it.

### Final deliverable: project presentation (after all phases)
- One PowerPoint deck (.pptx) summarising the whole project: the problem and users, the product and its
  differentiators, architecture, what each phase delivered, screenshots of the finished app, results
  (tests, security and compliance decisions) and what comes next.
- Built last, once every phase is done, so it describes the real finished product.

## 4. Cross-Cutting Concerns

- **Testing:** pytest for services (especially GST maths, stock ledger, idempotency); Playwright for POS and offline flows.
- **Money/GST:** single shared decimal utility; no floats anywhere; property tests for rounding.
- **Concurrency:** row locks on inventory during sale finalisation; unique constraints on invoice numbers and idempotency keys.
- **Security:** RBAC on every route, store-scoped queries, audit trail for price/stock/void actions.
- **Migrations:** Alembic only; no manual schema edits; seed script for tax rates and default roles.
- **Backups/ops:** nightly Postgres backup, restore tested before go-live.

## 5. Risks

| Risk | Mitigation |
|------|------------|
| GST compliance errors | Effective-dated config, professional review (D6), tests against worked examples. |
| Offline numbering/stock conflicts | Provisional receipts, server-authorised invoices, explicit conflict states. |
| Scope creep from competitor checklist | Stick to phased scope; differentiate on workflow quality. |
| Duplicate sales on retry | Idempotency keys + unique DB constraints from Phase 3. |
| Payment mis-recording | Payment status states (pending/confirmed/failed); never auto-success. |

## 6. Suggested Next Step

D1, D4, D5 resolved (recommended options). Remaining open: D2, D3, D6. Start Phase 0.

## 7. Parked items (agreed, not scheduled: do not forget)

| Item | Decision | Notes |
|------|----------|-------|
| **Admin page for user management** | **BUILT 2026-11-26.** No self-signup, ever: accounts are created only by an administrator on the Admin page. | Users tab (add, edit name/role/stores, reset password, sign out everywhere, deactivate; last sign-in shown), Activity tab (who did what, by name, filterable), generated temporary passwords shown once and enforced to be replaced at first sign-in (server-side). Still to do later: invitation by email. |
| Password reset by email | Not built | The login screen tells people to ask their administrator. Revisit with the admin page. |
| Login rate limiting | Not built | Needed before the app is exposed to the internet. |

