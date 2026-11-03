#!/usr/bin/env bash
# Nightly backup of the database and uploaded images. Keeps 14 days. COPY THE BACKUPS OFF THIS SERVER too
# (another machine or cloud storage): a backup on the same disk does not survive a dead disk.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
DEST="${BACKUP_DIR:-/var/backups/nk}"
STAMP="$(date +%Y%m%d-%H%M%S)"
mkdir -p "$DEST"
# pg_dump needs a plain postgresql:// URL (strip the "+psycopg" driver part)
pg_dump "${DATABASE_URL/+psycopg/}" --format=custom --file "$DEST/db-$STAMP.dump"
tar -czf "$DEST/uploads-$STAMP.tar.gz" -C "$(dirname "$UPLOAD_DIR")" "$(basename "$UPLOAD_DIR")"
find "$DEST" -type f \( -name 'db-*.dump' -o -name 'uploads-*.tar.gz' \) -mtime +14 -delete
echo "backup $STAMP done"
