# Wearstack --- Project Brief

## 1. What We Are Building

**Wearstack** is a clothing retail management system for an independent
clothing business in India.

The goal is to provide one application for day-to-day clothing shop
operations: billing, GST invoices, product and variant management,
inventory, purchases, customers, returns, reporting, and reliable
billing when internet connectivity is unavailable.

### Business and product decisions

-   **Business model:** Single-business deployment (not a multi-tenant
    SaaS product in the initial scope).
-   **Connectivity:** Hybrid --- online operation with offline billing
    and later synchronisation.
-   **Billing:** GST-enabled, for the Indian market.
-   **Architecture:** Modular monolith.
-   **Product approach:** Web-first application with PWA capabilities.
-   **Store structure:** Start with one business; keep the data model
    capable of supporting multiple stores/branches belonging to that
    business.
-   **Alteration management:** Explicitly out of scope. Do not build
    alteration workflows as part of the current product plan.

## 2. Target Users and Core Workflows

The initial product is intended for clothing retailers and their shop
staff.

Core workflows:

1.  Set up the business, store, users, roles and permissions.
2.  Create clothing products and variants such as size and colour.
3.  Manage SKUs, barcodes, prices, HSN codes and applicable GST rates.
4.  Record suppliers, purchases and received stock.
5.  Scan/search products and create sales at the POS.
6.  Generate GST-compliant invoices after validating applicable rules.
7.  Record cash, UPI, card and split payments.
8.  Process returns, exchanges and refunds while preserving the original
    sale history.
9.  Track stock balances and a complete stock-movement history.
10. View sales, inventory, customer and business reports.
11. Continue eligible billing workflows offline and synchronise
    transactions when connectivity returns.

## 3. Technology Stack

  -----------------------------------------------------------------------
  Layer                   Technology              Intended use
  ----------------------- ----------------------- -----------------------
  Frontend                React + TypeScript +    Web application and POS
                          Vite                    

  UI                      Tailwind CSS +          Application interface
                          shadcn/ui               

  Routing                 React Router            Frontend navigation

  Server state            TanStack Query          API data fetching and
                                                  caching

  UI/global state         Zustand                 Cart and application
                                                  state

  Forms and validation    React Hook Form + Zod   Frontend forms

  Backend                 Python + FastAPI        REST API and business
                                                  logic

  Validation              Pydantic v2             API schemas

  ORM                     SQLAlchemy 2.0          Database access

  Migrations              Alembic                 Database schema
                                                  migrations

  Primary database        PostgreSQL              Transactional business
                                                  data

  Offline storage         IndexedDB + Dexie.js    Cached catalogue and
                                                  pending offline sales

  Background jobs         Celery + Redis          Reports and
                                                  asynchronous tasks

  File storage            AWS S3                  Product images and
                                                  documents

  PDF generation          ReportLab               Invoice and report PDFs

  Barcode generation      python-barcode          Barcode generation

  Testing                 Pytest + Playwright     Backend and end-to-end
                                                  tests

  Containers              Docker                  Consistent development
                                                  and deployment

  CI/CD                   GitHub Actions          Automated checks and
                                                  deployment
  -----------------------------------------------------------------------

### Architecture principles

-   Start with a **modular monolith**, not microservices.
-   Keep business logic in service layers; routers should handle HTTP
    concerns.
-   Use repository modules for database access where useful.
-   PostgreSQL is the source of truth.
-   IndexedDB stores only the local data required for offline POS
    operation.
-   Use database transactions for sales, payments and inventory updates.
-   Use idempotency keys to prevent duplicate offline sales during
    retries.
-   Use decimal database types (`NUMERIC`) for monetary values, never
    floating-point types.
-   Preserve historical invoice line-item snapshots; do not let later
    product edits change old invoices.

## 4. Features We Are Targeting

The following five areas are the intended product differentiators. They
are priorities for product design and implementation, not claims that
competitors do not offer similar functionality.

### 4.1 Smart Inventory Intelligence

-   Product and variant inventory by size and colour.
-   Stock ageing and slow-moving/dead-stock identification.
-   Size-wise and colour-wise sales analysis.
-   Reorder suggestions based on sales velocity and available stock.
-   Low-stock alerts.
-   Inventory movement history and reconciliation.

### 4.2 Intelligent Returns and Exchanges

-   Find the original sale/invoice.
-   Exchange one size or colour for another.
-   Support partial returns and refunds.
-   Calculate price differences and additional payments/refunds.
-   Track return reasons and exchange history.
-   Update stock through auditable inventory movements.
-   Preserve the original invoice; use appropriate return/credit-note
    documents where required.

### 4.3 Reliable Offline-first POS

-   Cache products, variants, barcodes and required reference data
    locally.
-   Allow eligible sales to be recorded while offline.
-   Store pending transactions in IndexedDB.
-   Synchronise transactions when connectivity returns.
-   Use device and client transaction identifiers for idempotency.
-   Provide a sync status screen showing pending, successful and failed
    transactions.
-   Detect and report stock conflicts rather than silently overwriting
    server stock.
-   Distinguish provisional offline receipts from final
    server-authorised GST invoices.
-   Record payment status accurately; an attempted UPI/card payment must
    not automatically be treated as successful.

### 4.4 Business Intelligence

-   Daily, weekly and monthly sales summaries.
-   Revenue, discounts, returns and gross-margin reporting.
-   Best-selling products, categories, sizes and colours.
-   Slow-moving and ageing inventory.
-   Low-stock and replenishment insights.
-   Purchase and expense visibility.
-   Actionable recommendations for the shop owner.

Profit reporting must use reliable cost, discount, return and expense
data; revenue alone is not profit.

### 4.5 Customer Intelligence and Retention

-   Customer profiles and purchase history.
-   Frequently purchased brands, sizes and colours.
-   Customer purchase frequency and average order value.
-   Customer segmentation.
-   Loyalty points and rewards.
-   Relevant new-arrival and promotional campaigns.
-   WhatsApp notifications/campaigns with appropriate customer consent.

### Foundational capabilities

These are essential product capabilities, even though they are not the
five differentiators:

-   GST billing and invoice management.
-   Product, category and brand management.
-   Size/colour variants, SKU and barcode support.
-   Supplier and purchase management.
-   Inventory and stock movements.
-   Cash, UPI, card and split-payment recording.
-   Customer management.
-   User roles and permissions.
-   Sales, purchase and inventory reports.
-   Cash register/opening and closing workflows.

## 5. High-Level Application Modules

Backend modules planned for the modular monolith:

-   Authentication and authorisation
-   Business and store configuration
-   Users, roles and permissions
-   Products, categories, brands and variants
-   Inventory and stock movements
-   Suppliers and purchases
-   Sales and POS
-   Payments
-   GST and invoice documents
-   Returns, exchanges and refunds
-   Customers and loyalty
-   Reports and business intelligence
-   Offline synchronisation
-   Audit logging

## 6. Database Design --- Main Entities

The initial relational model is expected to include:

-   `businesses`
-   `stores`
-   `users`
-   `roles`
-   `permissions`
-   `role_permissions`
-   `user_store_access`
-   `categories`
-   `brands`
-   `products`
-   `product_variants`
-   `product_images`
-   `suppliers`
-   `purchases`
-   `purchase_items`
-   `inventory`
-   `stock_movements`
-   `customers`
-   `sales`
-   `sale_items`
-   `payments`
-   `sale_returns`
-   `return_items`
-   `refunds`
-   `tax_rates`
-   `invoice_sequences`
-   `gst_documents`
-   `expenses`
-   `cash_registers`
-   `cash_register_entries`
-   `devices`
-   `sync_operations`
-   `audit_logs`

Use UUID primary keys, foreign keys, appropriate unique constraints and
indexes. Inventory changes should be represented in a stock-movement
ledger and reflected in the current inventory balance within the same
database transaction.

## 7. Competitors Reviewed

We reviewed the following products at a market/product-positioning
level, primarily using vendor product pages and publicly available
product information. This was not a hands-on feature-by-feature product
test.

  --------------------------------------------------------------------------------------------------------------
  Competitor                                                                 Market positioning / areas reviewed
  -------------------------------------------------------------------------- -----------------------------------
  **Vyapar** --- https://vyaparapp.in/                                       Small-business billing, GST,
                                                                             accounting, inventory and barcode
                                                                             workflows

  **myBillBook** --- https://mybillbook.in/                                  Billing, GST, inventory, barcode
                                                                             and size/colour-related retail
                                                                             workflows

  **BUSY** --- https://busy.in/                                              Accounting, GST, inventory,
                                                                             garment-related stock and barcode
                                                                             capabilities

  **Marg ERP** --- https://margcompusoft.com/                                Retail/garment ERP, article, size,
                                                                             colour, barcode, purchase and
                                                                             supplier workflows

  **GoFrugal** --- https://www.gofrugal.com/retail/apparel-pos/              Apparel POS, retail inventory,
                                                                             promotions, multi-store operations
                                                                             and reporting

  **Ginesys** --- https://www.ginesys.in/                                    Fashion retail ERP, POS, inventory,
                                                                             omnichannel and multi-store
                                                                             operations

  **LOGIC ERP** ---                                                          Garment POS, style-size-colour
  https://www.logicerp.com/retail-pos-software/garment-pos-software-system   inventory, barcode and retail ERP
  --------------------------------------------------------------------------------------------------------------

### Competitive findings

-   GST billing, barcode scanning, size/colour variants, purchases,
    returns and reports are already available in parts of the competitor
    landscape.
-   Offline POS is also offered by established products; offline support
    alone is not a unique selling point.
-   Enterprise products such as GoFrugal, Ginesys and LOGIC ERP have
    extensive retail/fashion capabilities.
-   Wearstack should differentiate through the quality and simplicity of
    its combined workflows for independent clothing retailers, rather
    than merely matching a feature checklist.
-   Competitor plan limits, pricing, offline behaviour and exact
    workflow details must be verified directly before making comparative
    claims.

## 8. Product Positioning

**Working positioning statement:**

> Wearstack is a clothing retail management system that helps
> independent clothing shops run billing, inventory and customer
> operations from one place --- with intelligent stock insights and
> reliable offline-first POS.

The product should aim to be easy for shop owners and cashiers to learn,
quick at the billing counter, and trustworthy for inventory and
financial records.

## 9. Proposed Delivery Priorities

### Foundation / first usable release

-   Business and store setup.
-   Authentication and role permissions.
-   Product catalogue and size/colour variants.
-   SKU and barcode support.
-   Inventory and stock movements.
-   Supplier and purchase entry.
-   GST-aware POS billing.
-   Payment recording.
-   Invoice generation.
-   Basic sales and inventory reports.

### Next release

-   Offline sales queue and synchronisation.
-   Returns, exchanges and refunds.
-   Sync monitoring and conflict handling.
-   Cash register management.
-   Customer purchase history.

### Later releases

-   Smart inventory recommendations.
-   Advanced business intelligence.
-   Customer segmentation and loyalty.
-   WhatsApp integrations and campaigns.
-   More advanced forecasting.

## 10. Important Implementation Notes

-   Do not hardcode GST rates. Maintain effective-dated tax
    configuration and validate HSN classification, rate, place-of-supply
    and invoice rules against current Indian GST requirements.
-   Final GST invoice numbering and offline invoice handling require a
    compliant design. Offline receipts should remain provisional until
    finalised appropriately by the server, unless a separately validated
    numbering mechanism is implemented.
-   Keep sales and invoice history immutable after finalisation. Use
    returns, credit notes and adjustment documents rather than editing
    historical transactions.
-   Use idempotency for all synchronised offline transactions.
-   Do not silently permit overselling when offline stock may be stale.
    Define limits and reconciliation rules.
-   Validate payment success independently, especially for UPI and card
    payments.
-   Do not introduce microservices, AI features or complex integrations
    before the core retail workflows are reliable.
-   Alteration management is not part of the agreed scope.

------------------------------------------------------------------------

**Project name:** Wearstack\
**Initial market:** Indian clothing retail\
**Business model:** Single business\
**Connectivity:** Hybrid online/offline\
**Billing:** GST-enabled\
**Architecture:** Modular monolith\
**Primary differentiators:** Smart inventory intelligence, intelligent
returns/exchanges, reliable offline-first POS, business intelligence,
and customer intelligence/retention.
