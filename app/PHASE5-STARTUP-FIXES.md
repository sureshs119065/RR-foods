# Phase 5 startup fixes

This patch addresses the three startup errors from the Windows PowerShell log:

1. `requirements.txt`: replaced literal `\\n` text with real line breaks so pip can parse `pywebpush`.
2. `app/__init__.py`: removed the function-local `import logging` that shadowed the module-level import and caused `UnboundLocalError`.
3. Phase 5 migration: the merge migration now declares the three current Alembic branch heads (`aa71c4e9d302`, `1c4f8a9d2b70`, `7a91c3e5d802`) rather than redundantly listing an ancestor revision.

Before applying the migration to production, back up the database. Then run:

```powershell
pip install -r requirements.txt
flask db heads
flask db upgrade
flask db current
flask run
```

`flask db heads` should show one head after the Phase 5 merge revision is discovered. If your local `migrations/versions` directory contains additional migration files not present in this ZIP, inspect their revision graph before upgrading; do not delete migrations or use `stamp head` to bypass the graph.
