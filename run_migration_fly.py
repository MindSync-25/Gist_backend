"""Run DB migrations on production. Executed via Fly release_command.

Behavior:
- If MIGRATION_FILE is set, apply only that file.
- Otherwise, apply all .sql files under app/db in filename order.
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg2


def _ensure_migrations_table(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            filename TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )


def _table_exists(cur, table_name: str) -> bool:
    cur.execute(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = %s
        LIMIT 1
        """,
        (table_name,),
    )
    return cur.fetchone() is not None


def _is_migration_history_empty(cur) -> bool:
    cur.execute("SELECT COUNT(*) FROM schema_migrations")
    return int(cur.fetchone()[0]) == 0


def _list_migration_files(db_dir: Path, one_file: str | None) -> list[Path]:
    if one_file:
        target = db_dir / one_file
        if not target.exists():
            raise FileNotFoundError(f"Migration file not found: {target}")
        return [target]

    return sorted(p for p in db_dir.iterdir() if p.suffix.lower() == ".sql")


def main() -> None:
    database_url = os.environ["DATABASE_URL"]
    migration_file = os.environ.get("MIGRATION_FILE")
    db_dir = Path("app") / "db"

    migration_paths = _list_migration_files(db_dir, migration_file)
    if not migration_paths:
        print("No migration files found.")
        return

    conn = psycopg2.connect(database_url)
    try:
        with conn:
            with conn.cursor() as cur:
                _ensure_migrations_table(cur)

                applied_count = 0
                skipped_count = 0

                # Existing production DBs may already have historical schema changes
                # applied without rows in schema_migrations. In that case, replaying all
                # files can fail on legacy drift. Bootstrap by marking historical files as
                # applied and executing only the latest migration file.
                if migration_file is None and _is_migration_history_empty(cur) and _table_exists(cur, "users"):
                    latest = migration_paths[-1]
                    historical = migration_paths[:-1]

                    for path in historical:
                        cur.execute("INSERT INTO schema_migrations (filename) VALUES (%s)", (path.name,))
                        skipped_count += 1
                        print(f"Bootstrapped migration history: {path.name}")

                    migration_paths = [latest]
                    print(f"Legacy DB detected; applying latest migration only: {latest.name}")

                for path in migration_paths:
                    filename = path.name

                    cur.execute("SELECT 1 FROM schema_migrations WHERE filename = %s", (filename,))
                    if cur.fetchone() is not None:
                        skipped_count += 1
                        print(f"Skipping already-applied migration: {filename}")
                        continue

                    sql = path.read_text(encoding="utf-8")
                    cur.execute(sql)
                    cur.execute("INSERT INTO schema_migrations (filename) VALUES (%s)", (filename,))
                    applied_count += 1
                    print(f"Applied migration: {filename}")

        print(f"Migration run complete. Applied: {applied_count}, Skipped: {skipped_count}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
