#!/usr/bin/env bash
set -Eeuo pipefail
: "${DATABASE_URL:?DATABASE_URL must be set}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/rr-foods}"
KEEP_COPIES="${KEEP_COPIES:-7}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$BACKUP_DIR"
umask 077
TMP_FILE="$BACKUP_DIR/.rr-foods-$STAMP.dump.tmp"
FINAL_FILE="$BACKUP_DIR/rr-foods-$STAMP.dump"
DB_URL="${DATABASE_URL/postgresql+psycopg:/postgresql:}"
trap 'rm -f "$TMP_FILE"' EXIT
pg_dump --format=custom --no-owner --no-acl --dbname="$DB_URL" --file="$TMP_FILE"
mv "$TMP_FILE" "$FINAL_FILE"
mapfile -t OLD_FILES < <(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'rr-foods-*.dump' -printf '%T@ %p\\n' | sort -nr | tail -n +"$((KEEP_COPIES + 1))" | cut -d' ' -f2-)
for old_file in "${OLD_FILES[@]}"; do rm -f -- "$old_file"; done
echo "Backup created: $FINAL_FILE"
