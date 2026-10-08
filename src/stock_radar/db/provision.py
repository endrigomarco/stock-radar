import os

import psycopg
from psycopg import sql

from stock_radar.db.config import database_url


def main() -> None:
    roles = {
        "stock_radar_webhook": ("WEBHOOK_POSTGRES_PASSWORD", None), "stock_radar_reader": ("APP_POSTGRES_PASSWORD", "SELECT"),
        "stock_radar_collector": ("COLLECTOR_POSTGRES_PASSWORD", "SELECT, INSERT"), "stock_radar_monitor": ("MONITOR_POSTGRES_PASSWORD", None),
    }
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
                    cursor.execute("GRANT UPDATE (webhook_receipt_id, price_quote_id, occurred_at, observed_price, evidence_quality) ON trigger_events TO stock_radar_webhook")
                elif role == "stock_radar_monitor":
                    cursor.execute("GRANT SELECT ON sources, instruments, signal_observations, experiments, experiment_versions, tracking_runs, trigger_levels, trigger_events, price_quotes TO stock_radar_monitor")
                    cursor.execute("GRANT INSERT ON sources, price_quotes, trigger_levels, trigger_events TO stock_radar_monitor")
                    cursor.execute("GRANT UPDATE (status, admitted_at, reference_price, reference_at, reference_source_id, reference_evidence, activated_at, expires_at, price_coverage, coverage_evidence) ON tracking_runs TO stock_radar_monitor")
                else:
                    cursor.execute(sql.SQL("GRANT {} ON TABLE sources, instruments, collection_runs, signal_observations TO {}").format(sql.SQL(grants), identifier))
                    cursor.execute(sql.SQL("GRANT SELECT ON experiments, experiment_versions, tracking_runs, trigger_levels, trigger_events, price_quotes TO {}").format(identifier))
            cursor.execute("GRANT INSERT ON tracking_runs TO stock_radar_collector")
            cursor.execute("GRANT UPDATE (status) ON tracking_runs TO stock_radar_collector")
    print("Reader, collector, webhook and monitor database access configured.")


if __name__ == "__main__":
    main()
