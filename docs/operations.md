# Operating Wearstack

How to deploy, back up, restore and update the production stack. Everything here was exercised
end to end, including a full disaster drill (see "Restore drill").

## Deploy

1. A Linux server with Docker and Docker Compose, and a DNS name pointing at it.
2. Copy `.env.production.example` to `.env.production` and fill it in:
   - `POSTGRES_PASSWORD`: a long random password.
   - `JWT_SECRET`: `openssl rand -hex 32`. The app refuses to start in production with the dev default.
   - `DOMAIN`: your hostname (e.g. `shop.example.com`). Caddy fetches and renews a Let's Encrypt
     certificate automatically; ports 80 and 443 must be reachable. Use `:80` only behind another
     TLS terminator (then also set `COOKIE_SECURE=false` if that terminator speaks HTTP to it).
3. `docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build`
4. Open `https://<DOMAIN>`: the first visit runs the setup (business, GSTIN, first store, owner).

What it runs: `db` (Postgres, not exposed), `backend` (non-root, migrations run on start; no API
docs in production) and `web` (Caddy: the app at `/`, the API under `/api`, security headers).
Only ports 80 and 443 are published. Data lives in the `pgdata` and `media` volumes.

## Before you bill a real customer

- Enter your **GSTIN** (Stores page). Billing is blocked until the business or the store has one.
- Enter your **GST rates** (Products page). None are built in. Confirm the rates, the price
  slabs, and whether a slab is judged before or after discount (`GST_SLAB_BASIS`) with your
  accountant.
- Take a backup and **try a restore** (below) before relying on it.

## Backups

`scripts/backup.sh` writes a verified Postgres dump and a tar of uploaded images into `backups/`
(owner-readable only: they contain customer and financial data) and deletes files older than
`KEEP_DAYS` (default 14). It refuses to keep a dump it cannot read back.

Nightly at 02:30, as root's crontab:

    30 2 * * *  cd /opt/wearstack && ./scripts/backup.sh >> backups/backup.log 2>&1

A backup that lives only on the server dies with it. Copy `backups/` off the machine (another
server, object storage, an external disk) and keep at least one copy there.

## Restore

    ./scripts/restore.sh backups/wearstack-db-<stamp>.dump backups/wearstack-media-<stamp>.tar

It asks you to type `restore` (or pass `--yes`), stops the app, replaces the database and images,
and starts the app again. Afterwards check the latest invoice number and a stock level.

### Restore drill

Done once against the production stack, and worth repeating on a spare machine before go-live:
create data (a sale, stock, an uploaded image), back up, destroy the containers **and volumes**,
bring up an empty stack, restore. Verified: same store, same stock, the same invoice, the image
byte-for-byte identical, the append-only protections on sales and the ledger still enforced, and
the next invoice continuing the sequence with no gap or duplicate.

## Updating

    git pull
    ./scripts/backup.sh
    docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build

Migrations run automatically when the backend starts. Roll back by restoring the backup you took.

## Offline selling

Each till (a browser that has signed in once) keeps a copy of the catalogue, prices, barcodes,
stock and customers on the device, and can keep selling when the internet or the server is down.

- **Provisional receipts.** An offline sale gets a receipt like `OFF-A1B2-0007`. It says plainly that
  it is **not a GST tax invoice**. The numbered tax invoice is issued when the sale reaches the
  server (normally within seconds of the connection returning). Confirm with your accountant that
  handing a provisional receipt to the customer is acceptable for how you trade (plan item D6).
- **Syncing.** Queued sales are sent automatically when the connection is back, oldest first, and
  retried with backoff. A sale is never lost and never booked twice, even if the connection drops
  halfway through a request. A sale is dated when it really happened; its invoice is numbered when
  it syncs. Reports use the sale date.
- **Stock and prices.** A till will not sell more than the stock it knows about (its copy, less what
  it has already sold offline). If stock turns out to be short on the server (for example another
  till sold the last item), or a price changed, or the product was deactivated, or the sale is more
  than 7 days old, the sale is **held as a conflict** and nothing is booked. A manager decides on
  the **Sync** page: *Accept* books it as the customer was charged (a stock shortfall is corrected
  with a visible, reasoned stock adjustment; stock never goes negative), *Reject* voids it (a note
  is required), *Try again* re-runs it (for example after receiving stock).
- **How old a copy may be.** The catalogue refreshes about every 10 minutes while online. A till
  warns after 24 hours without a refresh and stops offline selling after 72 hours
  (`OFFLINE_WARN_HOURS`, `OFFLINE_BLOCK_HOURS`, `OFFLINE_MAX_SALE_AGE_DAYS`).
- **Opening with no connection.** The app is installable and loads from the device. A till that was
  signed in can reopen offline as the remembered user and sell. Anyone using that device offline
  acts as that user, so sign out on shared or unattended devices: signing out forgets the user but
  keeps unsent sales, which are sent after the next sign-in. The connection badge in the top bar
  and the **Sync** page show what is waiting.
- **Not available offline:** returns, purchases, stock changes, reports and administration.
- **Updates** never reload the app in the middle of a sale: a banner offers "Reload now".

## Things to know

- Sales, invoices, payments and the stock ledger cannot be edited or deleted, even with SQL.
  Corrections are new documents (returns and credit notes arrive in a later release).
- Reports count sales only; returns are subtracted once they exist. "Gross margin" excludes
  expenses.
- Login attempts are not rate limited yet; put the app behind a firewall or a rate-limiting
  proxy if it is exposed to the internet.
