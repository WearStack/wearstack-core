#!/usr/bin/env bash
# Backs up the database and uploaded images. Run it nightly (see docs/operations.md).
#   ./scripts/backup.sh                       # uses docker-compose.prod.yml + .env.production
#   COMPOSE="docker compose -p other ..." BACKUP_DIR=/mnt/backups KEEP_DAYS=30 ./scripts/backup.sh
set -euo pipefail
cd "$(dirname "$0")/.."

COMPOSE=${COMPOSE:-"docker compose -f docker-compose.prod.yml --env-file .env.production"}
OUT=${BACKUP_DIR:-backups}
KEEP_DAYS=${KEEP_DAYS:-14}
stamp=$(date +%Y%m%d-%H%M%S)
mkdir -p "$OUT"
umask 077  # backups contain customer and financial data

db="$OUT/wearstack-db-$stamp.dump"
media="$OUT/wearstack-media-$stamp.tar"

# Custom format: compressed, and restorable table by table.
$COMPOSE exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$db.partial"
# A dump that cannot be read back is worse than none: verify before keeping it.
if ! $COMPOSE exec -T db pg_restore --list < "$db.partial" > /dev/null; then
  rm -f "$db.partial"
  echo "Backup FAILED: the dump could not be read back." >&2
  exit 1
fi
mv "$db.partial" "$db"
$COMPOSE exec -T backend tar -C /app/media -cf - . > "$media"

# Keep the newest KEEP_DAYS days.
find "$OUT" -name 'wearstack-*' -type f -mtime +"$KEEP_DAYS" -delete

echo "Backup OK: $db ($(du -h "$db" | cut -f1)), $media ($(du -h "$media" | cut -f1))"
