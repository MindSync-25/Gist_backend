"""Run DB migration on production. Executed via Fly release_command."""
import os
import psycopg2

database_url = os.environ["DATABASE_URL"]
migration_file = os.environ.get("MIGRATION_FILE", "012_block_report.sql")
sql_path = os.path.join("app", "db", migration_file)

with open(sql_path) as f:
    sql = f.read()

conn = psycopg2.connect(database_url)
cur = conn.cursor()
cur.execute(sql)
conn.commit()
cur.close()
conn.close()
print(f"Migration {migration_file} applied successfully.")
