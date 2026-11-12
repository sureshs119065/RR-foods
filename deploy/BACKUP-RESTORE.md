# PostgreSQL backup and restore

Install PostgreSQL client tools (`pg_dump`, `pg_restore`) on the cron host.
Set `DATABASE_URL` and optionally `BACKUP_DIR` (default `/var/backups/rr-foods`).
The cron entry writes a custom-format dump daily and removes dumps older than seven days.
Keep the backup directory outside the public static/uploads folders with restrictive permissions.

## Restore
1. Stop application writes and take a safety dump of the current database.
2. Set `DATABASE_URL` to the target database.
3. Restore: `pg_restore --clean --if-exists --no-owner --no-acl --dbname="$DATABASE_URL" /path/to/rr-foods-TIMESTAMP.dump`
4. Run `flask db upgrade` if the restored DB predates the deployed migrations.
5. Start the app and verify `/health`.

Local retention does not protect against host loss. Copy encrypted backups to separate persistent storage.
