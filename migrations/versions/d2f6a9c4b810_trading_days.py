from datetime import date, time, timedelta
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd2f6a9c4b810'
down_revision: Union[str, Sequence[str], None] = 'c8a3f1d5e7b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

STANDARD_OPENS = time(10, 0)
STANDARD_CLOSES = time(17, 0)
SATURDAY = 5
CONSULTED_ON = date(2026, 10, 9)
WEEKEND = 'Weekend'

EXISTING_CONFIGURATION = 'existing_configuration'
NATIONAL_HOLIDAYS = 'national_holidays'

REFERENCE_2026 = (
    'Calendar previously coded in src/stock_radar/market_calendar.py. Closures and the late opening match '
    'B3 Oficio Circular 003/2026-VNC and 041/2026-VNC. The 10:00 to 17:00 hours are the configured '
    'simplification and are not the official grid for every date of the year.'
)
REFERENCE_NATIONAL = (
    'National holidays only: Lei 662/1949 as amended by Lei 10.607/2002, Lei 6.802/1980 and Lei 14.759/2023. '
    'No B3 calendar for this year was found on the consultation date. Optional days and municipal holidays '
    'are not included, so this may differ from the sessions B3 actually holds.'
)

CLOSED_2026 = {
    date(2026, 1, 1): 'Confraternização Universal',
    date(2026, 2, 16): 'Carnaval',
    date(2026, 2, 17): 'Carnaval',
    date(2026, 4, 3): 'Sexta-feira Santa',
    date(2026, 4, 21): 'Tiradentes',
    date(2026, 5, 1): 'Dia do Trabalho',
    date(2026, 6, 4): 'Corpus Christi',
    date(2026, 9, 7): 'Independência do Brasil',
    date(2026, 10, 12): 'Nossa Senhora Aparecida',
    date(2026, 11, 2): 'Finados',
    date(2026, 11, 20): 'Dia Nacional de Zumbi e da Consciência Negra',
    date(2026, 12, 24): 'Véspera de Natal',
    date(2026, 12, 25): 'Natal',
    date(2026, 12, 31): 'Expediente interno nas instituições bancárias',
}
LATE_OPENINGS_2026 = {date(2026, 2, 18): (time(13, 0), 'Quarta-feira de Cinzas')}

NATIONAL_HOLIDAYS_BY_MONTH_DAY = {
    (1, 1): 'Confraternização Universal',
    (4, 21): 'Tiradentes',
    (5, 1): 'Dia do Trabalho',
    (9, 7): 'Independência do Brasil',
    (10, 12): 'Nossa Senhora Aparecida',
    (11, 2): 'Finados',
    (11, 15): 'Proclamação da República',
    (11, 20): 'Dia Nacional de Zumbi e da Consciência Negra',
    (12, 25): 'Natal',
}
NATIONAL_YEARS = (2027, 2028)


def year_rows(year: int, closed: dict, late_openings: dict, origin: str, reference: str) -> list[dict]:
    rows = []
    day = date(year, 1, 1)
    while day.year == year:
        description = closed.get(day) or (WEEKEND if day.weekday() >= SATURDAY else None)
        is_open = description is None
        opens_at, opening_note = late_openings.get(day, (STANDARD_OPENS, None))
        rows.append({
            'day': day,
            'is_open': is_open,
            'opens_at': opens_at if is_open else None,
            'closes_at': STANDARD_CLOSES if is_open else None,
            'description': opening_note if is_open else description,
            'origin': origin,
            'source_reference': reference,
            'consulted_on': CONSULTED_ON,
        })
        day += timedelta(days=1)
    return rows


def national_closures(year: int) -> dict:
    return {date(year, month, day): name for (month, day), name in NATIONAL_HOLIDAYS_BY_MONTH_DAY.items()}


def upgrade() -> None:
    trading_days = op.create_table('trading_days',
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('is_open', sa.Boolean(), nullable=False),
    sa.Column('opens_at', sa.Time(), nullable=True),
    sa.Column('closes_at', sa.Time(), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('origin', sa.String(length=32), nullable=False),
    sa.Column('source_reference', sa.Text(), nullable=False),
    sa.Column('consulted_on', sa.Date(), nullable=False),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint(
        '(is_open AND opens_at IS NOT NULL AND closes_at IS NOT NULL AND opens_at < closes_at) '
        'OR (NOT is_open AND opens_at IS NULL AND closes_at IS NULL)',
        name=op.f('ck_trading_days_hours_match_open'),
    ),
    sa.CheckConstraint("origin IN ('existing_configuration', 'b3_official', 'national_holidays')", name=op.f('ck_trading_days_origin_valid')),
    sa.CheckConstraint('length(trim(source_reference)) > 0', name=op.f('ck_trading_days_source_reference_not_blank')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_trading_days')),
    sa.UniqueConstraint('day', name=op.f('uq_trading_days_day'))
    )
    rows = year_rows(2026, CLOSED_2026, LATE_OPENINGS_2026, EXISTING_CONFIGURATION, REFERENCE_2026)
    for year in NATIONAL_YEARS:
        rows.extend(year_rows(year, national_closures(year), {}, NATIONAL_HOLIDAYS, REFERENCE_NATIONAL))
    op.bulk_insert(trading_days, rows)


def downgrade() -> None:
    op.drop_table('trading_days')
