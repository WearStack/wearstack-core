#!/usr/bin/env bash
# Restores a backup, REPLACING the current database and images.
#   ./scripts/restore.sh backups/wearstack-db-<stamp>.dump [backups/wearstack-media-<stamp>.tar] [--yes]
set -euo pipefail
cd "$(dirname "$0")/.."

COMPOSE=${COMPOSE:-"docker compose -f docker-compose.prod.yml --env-file .env.production"}
db_dump=${1:?usage: restore.sh <db.dump> [media.tar] [--yes]}
media_tar=""
assume_yes=0
shift
for arg in "$@"; do
  if [ "$arg" = "--yes" ]; then assume_yes=1; else media_tar=$arg; fi
done
[ -f "$db_dump" ] || { echo "No such file: $db_dump" >&2; exit 1; }
[ -z "$media_tar" ] || [ -f "$media_tar" ] || { echo "No such file: $media_tar" >&2; exit 1; }

if [ "$assume_yes" -ne 1 ]; then
  echo "This REPLACES the current database (and images) with $db_dump."
  read -r -p "Type 'restore' to continue: " answer
  [ "$answer" = "restore" ] || { echo "Cancelled."; exit 1; }
fi

echo "Stopping the app (the database keeps running)..."
$COMPOSE stop web backend

echo "Recreating the database..."
$COMPOSE exec -T db sh -c 'psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 \
  -c "DROP DATABASE IF EXISTS \"$POSTGRES_DB\" WITH (FORCE)" \
  -c "CREATE DATABASE \"$POSTGRES_DB\" OWNER \"$POSTGRES_USER\""'

echo "Restoring data..."
$COMPOSE exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --exit-on-error' < "$db_dump"

if [ -n "$media_tar" ]; then
  echo "Restoring images..."
  $COMPOSE run --rm --no-deps -T --entrypoint sh backend -c 'rm -rf /app/media/* && tar -C /app/media -xf -' < "$media_tar"
fi

echo "Starting the app..."
$COMPOSE up -d backend web
echo "Restore complete. Check the app, then confirm the latest invoice and stock look right."
