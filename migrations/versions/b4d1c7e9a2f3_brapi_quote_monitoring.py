from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'b4d1c7e9a2f3'
down_revision: Union[str, Sequence[str], None] = '807ca9561c9f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EXPERIMENT_CODE = 'tradingview_losers_strong_buy'
REFERENCE_COLUMNS = (
    ('reference_price', sa.Numeric(precision=24, scale=8)),
    ('reference_at', sa.DateTime(timezone=True)),
    ('reference_source_id', sa.Uuid()),
    ('reference_evidence', postgresql.JSONB(astext_type=sa.Text())),
    ('expires_at', sa.DateTime(timezone=True)),
)
RULES = (
    '{"selection": {"signal_kind": "analyst_consensus", "normalized_rating": "strong_buy", "daily_change": "negative"}, '
    '"reference": "first_valid_quote_after_admission", "price_source": "brapi", "window_sessions": 20, '
    '"signed_percents": ["1", "2", "3", "-1", "-2", "-3"]}'
)


def upgrade() -> None:
    op.create_table('price_quotes',
    sa.Column('instrument_id', sa.Uuid(), nullable=False),
    sa.Column('source_id', sa.Uuid(), nullable=False),
    sa.Column('price', sa.Numeric(precision=24, scale=8), nullable=False),
    sa.Column('quoted_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('price > 0', name=op.f('ck_price_quotes_price_positive')),
    sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], name=op.f('fk_price_quotes_instrument_id_instruments'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['source_id'], ['sources.id'], name=op.f('fk_price_quotes_source_id_sources'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_price_quotes')),
    sa.UniqueConstraint('instrument_id', 'source_id', 'quoted_at', name=op.f('uq_price_quotes_instrument_id'))
    )
    op.create_index(op.f('ix_price_quotes_source_id'), 'price_quotes', ['source_id'], unique=False)

    op.add_column('tracking_runs', sa.Column('admitted_at', sa.DateTime(timezone=True), nullable=True))
    for name, column_type in REFERENCE_COLUMNS:
        op.alter_column('tracking_runs', name, existing_type=column_type, nullable=True)
    op.drop_constraint(op.f('ck_tracking_runs_status_valid'), 'tracking_runs', type_='check')
    op.create_check_constraint(op.f('ck_tracking_runs_status_valid'), 'tracking_runs', "status IN ('prepared', 'active', 'completed', 'cancelled', 'expired')")
    op.create_check_constraint(op.f('ck_tracking_runs_reference_all_or_none'), 'tracking_runs', 'num_nulls(reference_price, reference_at, reference_source_id, reference_evidence, expires_at) IN (0, 5)')
    op.create_check_constraint(op.f('ck_tracking_runs_started_requires_reference'), 'tracking_runs', "status NOT IN ('active', 'completed', 'expired') OR reference_price IS NOT NULL")

    op.add_column('trigger_events', sa.Column('price_quote_id', sa.Uuid(), nullable=True))
    op.alter_column('trigger_events', 'webhook_receipt_id', existing_type=sa.Uuid(), nullable=True)
    op.create_foreign_key(op.f('fk_trigger_events_price_quote_id_price_quotes'), 'trigger_events', 'price_quotes', ['price_quote_id'], ['id'], ondelete='RESTRICT')
    op.create_index(op.f('ix_trigger_events_price_quote_id'), 'trigger_events', ['price_quote_id'], unique=False)
    op.create_check_constraint(op.f('ck_trigger_events_evidence_single'), 'trigger_events', 'num_nonnulls(webhook_receipt_id, price_quote_id) = 1')

    connection = op.get_bind()
    connection.execute(sa.text(
        "INSERT INTO experiments (code, name, description) VALUES (:code, :name, :description) ON CONFLICT (code) DO NOTHING"
    ), {'code': EXPERIMENT_CODE, 'name': 'TradingView losers with Strong Buy consensus', 'description': 'Threshold crossings observed by polling after a negative daily change with Strong Buy analyst consensus.'})
    connection.execute(sa.text(
        "INSERT INTO experiment_versions (experiment_id, version, analysis_kind, rules) "
        "SELECT id, 1, 'threshold_crossing', CAST(:rules AS jsonb) FROM experiments WHERE code = :code "
        "ON CONFLICT (experiment_id, version) DO NOTHING"
    ), {'code': EXPERIMENT_CODE, 'rules': RULES})


def downgrade() -> None:
    connection = op.get_bind()
    blocking = connection.execute(sa.text(
        "SELECT (SELECT count(*) FROM tracking_runs WHERE reference_price IS NULL OR status = 'expired') "
        "+ (SELECT count(*) FROM trigger_events WHERE webhook_receipt_id IS NULL)"
    )).scalar_one()
    if blocking:
        raise RuntimeError(
            f'Downgrade refused: {blocking} polling tracking runs or quote-backed trigger events cannot be represented '
            'by the previous schema. Export and remove them deliberately before downgrading.'
        )
    connection.execute(sa.text(
        "DELETE FROM experiment_versions WHERE experiment_id IN (SELECT id FROM experiments WHERE code = :code) "
        "AND NOT EXISTS (SELECT 1 FROM tracking_runs WHERE tracking_runs.experiment_version_id = experiment_versions.id)"
    ), {'code': EXPERIMENT_CODE})
    connection.execute(sa.text(
        "DELETE FROM experiments WHERE code = :code "
        "AND NOT EXISTS (SELECT 1 FROM experiment_versions WHERE experiment_versions.experiment_id = experiments.id)"
    ), {'code': EXPERIMENT_CODE})

    op.drop_constraint(op.f('ck_trigger_events_evidence_single'), 'trigger_events', type_='check')
    op.drop_index(op.f('ix_trigger_events_price_quote_id'), table_name='trigger_events')
    op.drop_constraint(op.f('fk_trigger_events_price_quote_id_price_quotes'), 'trigger_events', type_='foreignkey')
    op.alter_column('trigger_events', 'webhook_receipt_id', existing_type=sa.Uuid(), nullable=False)
    op.drop_column('trigger_events', 'price_quote_id')

    op.drop_constraint(op.f('ck_tracking_runs_started_requires_reference'), 'tracking_runs', type_='check')
    op.drop_constraint(op.f('ck_tracking_runs_reference_all_or_none'), 'tracking_runs', type_='check')
    op.drop_constraint(op.f('ck_tracking_runs_status_valid'), 'tracking_runs', type_='check')
    op.create_check_constraint(op.f('ck_tracking_runs_status_valid'), 'tracking_runs', "status IN ('prepared', 'active', 'completed', 'cancelled')")
    for name, column_type in REFERENCE_COLUMNS:
        op.alter_column('tracking_runs', name, existing_type=column_type, nullable=False)
    op.drop_column('tracking_runs', 'admitted_at')

    op.drop_index(op.f('ix_price_quotes_source_id'), table_name='price_quotes')
    op.drop_table('price_quotes')
