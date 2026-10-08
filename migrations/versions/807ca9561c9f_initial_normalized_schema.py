from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '807ca9561c9f'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('experiments',
    sa.Column('code', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('length(trim(code)) > 0', name=op.f('ck_experiments_code_not_blank')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_experiments')),
    sa.UniqueConstraint('code', name=op.f('uq_experiments_code'))
    )
    op.create_table('instruments',
    sa.Column('exchange', sa.String(length=32), nullable=False),
    sa.Column('symbol', sa.String(length=32), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name=op.f('ck_instruments_currency_code')),
    sa.CheckConstraint('length(trim(exchange)) > 0 AND length(trim(symbol)) > 0', name=op.f('ck_instruments_identity_not_blank')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_instruments')),
    sa.UniqueConstraint('exchange', 'symbol', name=op.f('uq_instruments_exchange'))
    )
    op.create_table('sources',
    sa.Column('code', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('base_url', sa.Text(), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('length(trim(code)) > 0', name=op.f('ck_sources_code_not_blank')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sources')),
    sa.UniqueConstraint('code', name=op.f('uq_sources_code'))
    )
    op.create_table('collection_runs',
    sa.Column('source_id', sa.Uuid(), nullable=False),
    sa.Column('client_collection_id', sa.Uuid(), nullable=False),
    sa.Column('payload_hash', sa.String(length=64), nullable=False),
    sa.Column('source_url', sa.Text(), nullable=False),
    sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('market_session_date', sa.Date(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('source_total', sa.Integer(), nullable=True),
    sa.Column('filters', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_collection_runs_payload_hash_sha256')),
    sa.CheckConstraint("status IN ('complete', 'partial', 'failed')", name=op.f('ck_collection_runs_status_valid')),
    sa.CheckConstraint('source_total IS NULL OR source_total >= 0', name=op.f('ck_collection_runs_source_total_nonnegative')),
    sa.ForeignKeyConstraint(['source_id'], ['sources.id'], name=op.f('fk_collection_runs_source_id_sources'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_collection_runs')),
    sa.UniqueConstraint('source_id', 'client_collection_id', name=op.f('uq_collection_runs_source_id'))
    )
    op.create_index('ix_collection_runs_source_observed', 'collection_runs', ['source_id', 'observed_at'], unique=False)
    op.create_table('experiment_versions',
    sa.Column('experiment_id', sa.Uuid(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('analysis_kind', sa.String(length=64), nullable=False),
    sa.Column('rules', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("jsonb_typeof(rules) = 'object'", name=op.f('ck_experiment_versions_rules_object')),
    sa.CheckConstraint('length(trim(analysis_kind)) > 0', name=op.f('ck_experiment_versions_analysis_kind_not_blank')),
    sa.CheckConstraint('version > 0', name=op.f('ck_experiment_versions_version_positive')),
    sa.ForeignKeyConstraint(['experiment_id'], ['experiments.id'], name=op.f('fk_experiment_versions_experiment_id_experiments'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_experiment_versions')),
    sa.UniqueConstraint('experiment_id', 'version', name=op.f('uq_experiment_versions_experiment_id'))
    )
    op.create_table('webhook_receipts',
    sa.Column('source_id', sa.Uuid(), nullable=False),
    sa.Column('deduplication_key', sa.String(length=200), nullable=False),
    sa.Column('provider_event_id', sa.String(length=200), nullable=True),
    sa.Column('reported_alert_mapping_id', sa.Uuid(), nullable=True),
    sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('source_event_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('sanitized_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.String(length=16), server_default='pending', nullable=False),
    sa.Column('processing_attempts', sa.Integer(), server_default='0', nullable=False),
    sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error_code', sa.String(length=80), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('pending', 'processed', 'unmapped', 'failed')", name=op.f('ck_webhook_receipts_status_valid')),
    sa.CheckConstraint('length(trim(deduplication_key)) > 0', name=op.f('ck_webhook_receipts_deduplication_key_not_blank')),
    sa.CheckConstraint('processing_attempts >= 0', name=op.f('ck_webhook_receipts_attempts_nonnegative')),
    sa.ForeignKeyConstraint(['source_id'], ['sources.id'], name=op.f('fk_webhook_receipts_source_id_sources'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_webhook_receipts')),
    sa.UniqueConstraint('source_id', 'deduplication_key', name=op.f('uq_webhook_receipts_source_id'))
    )
    op.create_index(op.f('ix_webhook_receipts_reported_alert_mapping_id'), 'webhook_receipts', ['reported_alert_mapping_id'], unique=False)
    op.create_index('ix_webhook_receipts_status_received', 'webhook_receipts', ['status', 'received_at'], unique=False)
    op.create_table('signal_observations',
    sa.Column('collection_run_id', sa.Uuid(), nullable=False),
    sa.Column('instrument_id', sa.Uuid(), nullable=False),
    sa.Column('signal_kind', sa.String(length=64), nullable=False),
    sa.Column('source_symbol', sa.String(length=80), nullable=False),
    sa.Column('source_column', sa.String(length=120), nullable=True),
    sa.Column('original_rating', sa.Text(), nullable=True),
    sa.Column('normalized_rating', sa.String(length=64), nullable=True),
    sa.Column('normalization_version', sa.String(length=64), nullable=False),
    sa.Column('observed_price', sa.Numeric(precision=24, scale=8), nullable=True),
    sa.Column('daily_change_percent', sa.Numeric(precision=12, scale=6), nullable=True),
    sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('source_published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('parse_status', sa.String(length=16), nullable=False),
    sa.Column('raw_evidence', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('quality_details', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("parse_status IN ('valid', 'partial', 'invalid')", name=op.f('ck_signal_observations_parse_status_valid')),
    sa.CheckConstraint('daily_change_percent IS NULL OR daily_change_percent >= -100', name=op.f('ck_signal_observations_change_valid')),
    sa.CheckConstraint('length(trim(signal_kind)) > 0', name=op.f('ck_signal_observations_signal_kind_not_blank')),
    sa.CheckConstraint('observed_price IS NULL OR observed_price > 0', name=op.f('ck_signal_observations_price_positive')),
    sa.ForeignKeyConstraint(['collection_run_id'], ['collection_runs.id'], name=op.f('fk_signal_observations_collection_run_id_collection_runs'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], name=op.f('fk_signal_observations_instrument_id_instruments'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_signal_observations')),
    sa.UniqueConstraint('collection_run_id', 'instrument_id', 'signal_kind', name=op.f('uq_signal_observations_collection_run_id'))
    )
    op.create_index(op.f('ix_signal_observations_instrument_id'), 'signal_observations', ['instrument_id'], unique=False)
    op.create_table('tracking_runs',
    sa.Column('client_tracking_id', sa.Uuid(), nullable=False),
    sa.Column('payload_hash', sa.String(length=64), nullable=False),
    sa.Column('signal_observation_id', sa.Uuid(), nullable=False),
    sa.Column('experiment_version_id', sa.Uuid(), nullable=False),
    sa.Column('reference_price', sa.Numeric(precision=24, scale=8), nullable=False),
    sa.Column('reference_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('reference_source_id', sa.Uuid(), nullable=False),
    sa.Column('reference_evidence', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('status', sa.String(length=16), server_default='prepared', nullable=False),
    sa.Column('price_coverage', sa.String(length=16), server_default='unknown', nullable=False),
    sa.Column('coverage_evidence', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_tracking_runs_payload_hash_sha256')),
    sa.CheckConstraint("price_coverage IN ('unknown', 'partial', 'verified')", name=op.f('ck_tracking_runs_price_coverage_valid')),
    sa.CheckConstraint("status != 'active' OR activated_at IS NOT NULL", name=op.f('ck_tracking_runs_active_requires_activation')),
    sa.CheckConstraint("status IN ('prepared', 'active', 'completed', 'cancelled')", name=op.f('ck_tracking_runs_status_valid')),
    sa.CheckConstraint('activated_at IS NULL OR (activated_at >= reference_at AND activated_at < expires_at)', name=op.f('ck_tracking_runs_activation_window')),
    sa.CheckConstraint('expires_at > reference_at', name=op.f('ck_tracking_runs_expiry_after_reference')),
    sa.CheckConstraint('reference_price > 0', name=op.f('ck_tracking_runs_reference_positive')),
    sa.ForeignKeyConstraint(['experiment_version_id'], ['experiment_versions.id'], name=op.f('fk_tracking_runs_experiment_version_id_experiment_versions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['reference_source_id'], ['sources.id'], name=op.f('fk_tracking_runs_reference_source_id_sources'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['signal_observation_id'], ['signal_observations.id'], name=op.f('fk_tracking_runs_signal_observation_id_signal_observations'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tracking_runs')),
    sa.UniqueConstraint('client_tracking_id', name=op.f('uq_tracking_runs_client_tracking_id'))
    )
    op.create_index(op.f('ix_tracking_runs_experiment_version_id'), 'tracking_runs', ['experiment_version_id'], unique=False)
    op.create_index(op.f('ix_tracking_runs_reference_source_id'), 'tracking_runs', ['reference_source_id'], unique=False)
    op.create_index(op.f('ix_tracking_runs_signal_observation_id'), 'tracking_runs', ['signal_observation_id'], unique=False)
    op.create_table('trigger_levels',
    sa.Column('tracking_run_id', sa.Uuid(), nullable=False),
    sa.Column('signed_percent', sa.Numeric(precision=12, scale=6), nullable=False),
    sa.Column('mathematical_price', sa.Numeric(precision=38, scale=16), nullable=False),
    sa.Column('configured_price', sa.Numeric(precision=24, scale=8), nullable=True),
    sa.Column('rounding_policy', sa.String(length=64), nullable=True),
    sa.Column('alert_mapping_id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('alert_source_id', sa.Uuid(), nullable=True),
    sa.Column('alert_active_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('alert_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('alert_coverage', sa.String(length=16), server_default='unknown', nullable=False),
    sa.Column('alert_evidence', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("alert_coverage IN ('unknown', 'partial', 'verified')", name=op.f('ck_trigger_levels_alert_coverage_valid')),
    sa.CheckConstraint('alert_expires_at IS NULL OR (alert_active_at IS NOT NULL AND alert_expires_at > alert_active_at)', name=op.f('ck_trigger_levels_alert_window')),
    sa.CheckConstraint('mathematical_price > 0 AND (configured_price IS NULL OR configured_price > 0)', name=op.f('ck_trigger_levels_prices_positive')),
    sa.CheckConstraint('signed_percent > -100 AND signed_percent != 0', name=op.f('ck_trigger_levels_percent_valid')),
    sa.ForeignKeyConstraint(['alert_source_id'], ['sources.id'], name=op.f('fk_trigger_levels_alert_source_id_sources'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tracking_run_id'], ['tracking_runs.id'], name=op.f('fk_trigger_levels_tracking_run_id_tracking_runs'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_trigger_levels')),
    sa.UniqueConstraint('alert_mapping_id', name=op.f('uq_trigger_levels_alert_mapping_id')),
    sa.UniqueConstraint('tracking_run_id', 'signed_percent', name=op.f('uq_trigger_levels_tracking_run_id'))
    )
    op.create_index(op.f('ix_trigger_levels_alert_source_id'), 'trigger_levels', ['alert_source_id'], unique=False)
    op.create_table('trigger_events',
    sa.Column('trigger_level_id', sa.Uuid(), nullable=False),
    sa.Column('webhook_receipt_id', sa.Uuid(), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('observed_price', sa.Numeric(precision=24, scale=8), nullable=True),
    sa.Column('evidence_quality', sa.String(length=16), server_default='unknown', nullable=False),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("evidence_quality IN ('timestamped', 'coarse', 'unknown')", name=op.f('ck_trigger_events_evidence_quality_valid')),
    sa.CheckConstraint('observed_price IS NULL OR observed_price > 0', name=op.f('ck_trigger_events_price_positive')),
    sa.ForeignKeyConstraint(['trigger_level_id'], ['trigger_levels.id'], name=op.f('fk_trigger_events_trigger_level_id_trigger_levels'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['webhook_receipt_id'], ['webhook_receipts.id'], name=op.f('fk_trigger_events_webhook_receipt_id_webhook_receipts'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_trigger_events')),
    sa.UniqueConstraint('trigger_level_id', name=op.f('uq_trigger_events_trigger_level_id'))
    )
    op.create_index(op.f('ix_trigger_events_webhook_receipt_id'), 'trigger_events', ['webhook_receipt_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_trigger_events_webhook_receipt_id'), table_name='trigger_events')
    op.drop_table('trigger_events')
    op.drop_index(op.f('ix_trigger_levels_alert_source_id'), table_name='trigger_levels')
    op.drop_table('trigger_levels')
    op.drop_index(op.f('ix_tracking_runs_signal_observation_id'), table_name='tracking_runs')
    op.drop_index(op.f('ix_tracking_runs_reference_source_id'), table_name='tracking_runs')
    op.drop_index(op.f('ix_tracking_runs_experiment_version_id'), table_name='tracking_runs')
    op.drop_table('tracking_runs')
    op.drop_index(op.f('ix_signal_observations_instrument_id'), table_name='signal_observations')
    op.drop_table('signal_observations')
    op.drop_index('ix_webhook_receipts_status_received', table_name='webhook_receipts')
    op.drop_index(op.f('ix_webhook_receipts_reported_alert_mapping_id'), table_name='webhook_receipts')
    op.drop_table('webhook_receipts')
    op.drop_table('experiment_versions')
    op.drop_index('ix_collection_runs_source_observed', table_name='collection_runs')
    op.drop_table('collection_runs')
    op.drop_table('sources')
    op.drop_table('instruments')
    op.drop_table('experiments')
