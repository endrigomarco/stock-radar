from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c8a3f1d5e7b2'
down_revision: Union[str, Sequence[str], None] = 'b4d1c7e9a2f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('collection_runs', sa.Column('rows_examined', sa.Integer(), nullable=True))
    op.create_check_constraint(
        op.f('ck_collection_runs_rows_examined_nonnegative'),
        'collection_runs',
        'rows_examined IS NULL OR rows_examined >= 0',
    )


def downgrade() -> None:
    op.drop_constraint(op.f('ck_collection_runs_rows_examined_nonnegative'), 'collection_runs', type_='check')
    op.drop_column('collection_runs', 'rows_examined')
