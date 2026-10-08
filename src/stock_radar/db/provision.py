import os

import psycopg
from psycopg import sql

from stock_radar.db.config import database_url


def main() -> None:
    roles = {"stock_radar_webhook": ("WEBHOOK_POSTGRES_PASSWORD", None), "stock_radar_reader": ("APP_POSTGRES_PASSWORD", "SELECT"), "stock_radar_collector": ("COLLECTOR_POSTGRES_PASSWORD", "SELECT, INSERT")}
    url = database_url()
    with psycopg.connect(host=url.host, port=url.port, user=url.username, password=url.password, dbname=url.database) as connection:
        with connection.cursor() as cursor:
            for role, (variable, grants) in roles.items():
                password = os.environ.get(variable, "")
                if len(password) < 32:
                    raise ValueError(f"{variable} must contain at least 32 characters")
                identifier = sql.Identifier(role)
                cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
                if cursor.fetchone() is None:
                    cursor.execute(sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT").format(identifier))
                cursor.execute(sql.SQL("ALTER ROLE {} PASSWORD {}").format(identifier, sql.Literal(password)))
                cursor.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(url.database), identifier))
                cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(identifier))
                if role == "stock_radar_webhook":
                    cursor.execute("GRANT SELECT ON sources, tracking_runs, trigger_levels, webhook_receipts, trigger_events TO stock_radar_webhook")
                    cursor.execute("GRANT INSERT ON webhook_receipts, trigger_events TO stock_radar_webhook")
                    cursor.execute("GRANT UPDATE (status, processing_attempts, processed_at, last_error_code) ON webhook_receipts TO stock_radar_webhook")
                    cursor.execute("GRANT UPDATE (webhook_receipt_id, occurred_at, observed_price, evidence_quality) ON trigger_events TO stock_radar_webhook")
                else:
                    cursor.execute(sql.SQL("GRANT {} ON TABLE sources, instruments, collection_runs, signal_observations TO {}").format(sql.SQL(grants), identifier))
    print("Reader, collector and webhook database access configured.")


if __name__ == "__main__":
    main()
