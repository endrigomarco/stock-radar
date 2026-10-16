from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'e7c4b2a9d1f6'
down_revision: Union[str, Sequence[str], None] = 'd2f6a9c4b810'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EXPERIMENT_CODE = 'tradingview_losers_strong_buy'
SELECTION_RULES = (
    '{"candidate_selection": {"mode": "assisted", "max_new_per_session": 3, "criteria_version": "selection-v1", '
    '"reference_after_decision": true, "late_decisions": "allowed_and_marked"}}'
)


def upgrade() -> None:
    op.add_column('signal_observations', sa.Column('volume', sa.Numeric(precision=24, scale=0), nullable=True))
    op.add_column('signal_observations', sa.Column('sector', sa.String(length=120), nullable=True))
    op.create_check_constraint(op.f('ck_signal_observations_volume_nonnegative'), 'signal_observations', 'volume IS NULL OR volume >= 0')

    op.add_column('collection_runs', sa.Column('experiment_version_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(op.f('fk_collection_runs_experiment_version_id_experiment_versions'), 'collection_runs', 'experiment_versions', ['experiment_version_id'], ['id'], ondelete='RESTRICT')
    op.create_index(op.f('ix_collection_runs_experiment_version_id'), 'collection_runs', ['experiment_version_id'], unique=False)

    op.create_table('candidate_selections',
    sa.Column('client_selection_id', sa.Uuid(), nullable=False),
    sa.Column('payload_hash', sa.String(length=64), nullable=False),
    sa.Column('experiment_version_id', sa.Uuid(), nullable=False),
    sa.Column('market_session_date', sa.Date(), nullable=False),
    sa.Column('criteria_version', sa.String(length=64), nullable=False),
    sa.Column('ranking_basis', sa.String(length=16), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('no_selection_reason', sa.Text(), nullable=True),
    sa.Column('plugin_version', sa.String(length=32), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('late', sa.Boolean(), nullable=False),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_candidate_selections_payload_hash_sha256')),
    sa.CheckConstraint('length(trim(criteria_version)) > 0', name=op.f('ck_candidate_selections_criteria_version_not_blank')),
    sa.CheckConstraint("ranking_basis IN ('full', 'limited')", name=op.f('ck_candidate_selections_ranking_basis_valid')),
    sa.ForeignKeyConstraint(['experiment_version_id'], ['experiment_versions.id'], name=op.f('fk_candidate_selections_experiment_version_id_experiment_versions'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_candidate_selections')),
    sa.UniqueConstraint('client_selection_id', name=op.f('uq_candidate_selections_client_selection_id'))
    )
    op.create_index('ix_candidate_selections_version_session', 'candidate_selections', ['experiment_version_id', 'market_session_date'], unique=False)

    op.create_table('candidate_decisions',
    sa.Column('experiment_version_id', sa.Uuid(), nullable=False),
    sa.Column('market_session_date', sa.Date(), nullable=False),
    sa.Column('instrument_id', sa.Uuid(), nullable=False),
    sa.Column('signal_observation_id', sa.Uuid(), nullable=False),
    sa.Column('candidate_selection_id', sa.Uuid(), nullable=True),
    sa.Column('outcome', sa.String(length=24), nullable=False),
    sa.Column('reason_code', sa.String(length=48), nullable=True),
    sa.Column('rank', sa.Integer(), nullable=True),
    sa.Column('baseline_rank', sa.Integer(), nullable=True),
    sa.Column('slot', sa.Integer(), nullable=True),
    sa.Column('tracking_run_id', sa.Uuid(), nullable=True),
    sa.Column('rationale', sa.Text(), nullable=True),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("outcome IN ('pending', 'selected', 'not_selected', 'not_assessable', 'already_tracked')", name=op.f('ck_candidate_decisions_outcome_valid')),
    sa.CheckConstraint("(outcome = 'selected') = (slot IS NOT NULL)", name=op.f('ck_candidate_decisions_slot_matches_selection')),
    sa.CheckConstraint('slot IS NULL OR slot > 0', name=op.f('ck_candidate_decisions_slot_positive')),
    sa.CheckConstraint('rank IS NULL OR rank > 0', name=op.f('ck_candidate_decisions_rank_positive')),
    sa.CheckConstraint("outcome NOT IN ('selected', 'already_tracked') OR tracking_run_id IS NOT NULL", name=op.f('ck_candidate_decisions_run_required')),
    sa.CheckConstraint("(outcome = 'pending') = (decided_at IS NULL)", name=op.f('ck_candidate_decisions_decided_matches_outcome')),
    sa.CheckConstraint("jsonb_typeof(details) = 'object'", name=op.f('ck_candidate_decisions_details_object')),
    sa.ForeignKeyConstraint(['experiment_version_id'], ['experiment_versions.id'], name=op.f('fk_candidate_decisions_experiment_version_id_experiment_versions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], name=op.f('fk_candidate_decisions_instrument_id_instruments'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['signal_observation_id'], ['signal_observations.id'], name=op.f('fk_candidate_decisions_signal_observation_id_signal_observations'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['candidate_selection_id'], ['candidate_selections.id'], name=op.f('fk_candidate_decisions_candidate_selection_id_candidate_selections'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tracking_run_id'], ['tracking_runs.id'], name=op.f('fk_candidate_decisions_tracking_run_id_tracking_runs'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_candidate_decisions')),
    sa.UniqueConstraint('experiment_version_id', 'market_session_date', 'instrument_id', name='uq_candidate_decisions_candidate'),
    sa.UniqueConstraint('experiment_version_id', 'market_session_date', 'slot', name='uq_candidate_decisions_slot')
    )
    op.create_index(op.f('ix_candidate_decisions_instrument_id'), 'candidate_decisions', ['instrument_id'], unique=False)
    op.create_index(op.f('ix_candidate_decisions_signal_observation_id'), 'candidate_decisions', ['signal_observation_id'], unique=False)
    op.create_index(op.f('ix_candidate_decisions_candidate_selection_id'), 'candidate_decisions', ['candidate_selection_id'], unique=False)
    op.create_index(op.f('ix_candidate_decisions_tracking_run_id'), 'candidate_decisions', ['tracking_run_id'], unique=False)

    op.get_bind().execute(sa.text(
        "INSERT INTO experiment_versions (experiment_id, version, analysis_kind, rules) "
        "SELECT experiment_id, 2, analysis_kind, rules || CAST(:rules AS jsonb) FROM experiment_versions "
        "WHERE version = 1 AND experiment_id IN (SELECT id FROM experiments WHERE code = :code) "
        "ON CONFLICT (experiment_id, version) DO NOTHING"
    ), {'code': EXPERIMENT_CODE, 'rules': SELECTION_RULES})


def downgrade() -> None:
    connection = op.get_bind()
    blocking = connection.execute(sa.text(
        "SELECT (SELECT count(*) FROM candidate_decisions) + (SELECT count(*) FROM candidate_selections) "
        "+ (SELECT count(*) FROM signal_observations WHERE volume IS NOT NULL OR sector IS NOT NULL) "
        "+ (SELECT count(*) FROM collection_runs JOIN experiment_versions ON experiment_versions.id = collection_runs.experiment_version_id "
        "WHERE experiment_versions.rules ? 'candidate_selection') "
        "+ (SELECT count(*) FROM tracking_runs JOIN experiment_versions ON experiment_versions.id = tracking_runs.experiment_version_id "
        "WHERE experiment_versions.rules ? 'candidate_selection')"
    )).scalar_one()
    if blocking:
        raise RuntimeError(
            f'Downgrade refused: {blocking} records belong to assisted candidate selection and cannot be represented '
            'by the previous schema. Export and remove them deliberately before downgrading.'
        )
    connection.execute(sa.text(
        "DELETE FROM experiment_versions WHERE rules ? 'candidate_selection' "
        "AND experiment_id IN (SELECT id FROM experiments WHERE code = :code)"
    ), {'code': EXPERIMENT_CODE})

    op.drop_index(op.f('ix_candidate_decisions_tracking_run_id'), table_name='candidate_decisions')
    op.drop_index(op.f('ix_candidate_decisions_candidate_selection_id'), table_name='candidate_decisions')
    op.drop_index(op.f('ix_candidate_decisions_signal_observation_id'), table_name='candidate_decisions')
    op.drop_index(op.f('ix_candidate_decisions_instrument_id'), table_name='candidate_decisions')
    op.drop_table('candidate_decisions')
    op.drop_index('ix_candidate_selections_version_session', table_name='candidate_selections')
    op.drop_table('candidate_selections')

    op.drop_index(op.f('ix_collection_runs_experiment_version_id'), table_name='collection_runs')
    op.drop_constraint(op.f('fk_collection_runs_experiment_version_id_experiment_versions'), 'collection_runs', type_='foreignkey')
    op.drop_column('collection_runs', 'experiment_version_id')

    op.drop_constraint(op.f('ck_signal_observations_volume_nonnegative'), 'signal_observations', type_='check')
    op.drop_column('signal_observations', 'sector')
    op.drop_column('signal_observations', 'volume')
