"""Compare registered Python models with PostgreSQL and run reviewed revisions."""

from logging.config import fileConfig

from alembic import context
from alembic.migration import MigrationContext
from alembic.operations.ops import MigrationScript
from sqlalchemy import create_engine, pool

from stock_radar.db.config import database_url
from stock_radar.db.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def skip_empty_revision(
    migration_context: MigrationContext,
    revision: tuple[str, ...],
    directives: list[MigrationScript],
) -> None:
    """Do not create an empty revision when autogenerate finds no changes."""
    if getattr(config.cmd_opts, "autogenerate", False):
        if directives and directives[0].upgrade_ops.is_empty():
            directives.clear()
            config.print_stdout("No model changes detected; no revision created.")


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
                process_revision_directives=skip_empty_revision,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
