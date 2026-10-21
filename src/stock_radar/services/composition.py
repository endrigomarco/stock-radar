from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import groupby
from uuid import UUID


@dataclass(frozen=True)
class Candidate:
    run_id: UUID
    decided_at: datetime
    entry_at: datetime | None
    entry_confirmed: bool = True


@dataclass(frozen=True)
class Composition:
    participants: tuple[UUID, ...]
    outside: tuple[UUID, ...]
    first_entry_at: datetime | None
    final: bool


def compose(candidates: list[Candidate], cut: datetime, max_quote_age: timedelta) -> Composition:
    participants: list[UUID] = []
    outside: list[UUID] = []
    first_entry: datetime | None = None
    unconfirmed_entry: datetime | None = None
    unknown_before = False
    settled = True
    ordered = sorted((item for item in candidates if item.decided_at <= cut), key=lambda item: (item.decided_at, str(item.run_id)))
    for decided_at, group in groupby(ordered, key=lambda item: item.decided_at):
        members = list(group)
        if first_entry is not None and decided_at >= first_entry:
            outside.extend(item.run_id for item in members)
            continue
        if unknown_before and decided_at > cut - max_quote_age:
            settled = False
        if unconfirmed_entry is not None and decided_at >= unconfirmed_entry:
            settled = False
        participants.extend(item.run_id for item in members)
        first_entry = _earliest(first_entry, [item.entry_at for item in members if item.entry_at is not None and item.entry_confirmed])
        unconfirmed_entry = _earliest(unconfirmed_entry, [item.entry_at for item in members if item.entry_at is not None and not item.entry_confirmed])
        unknown_before = unknown_before or any(item.entry_at is None for item in members)
    return Composition(tuple(participants), tuple(outside), first_entry, settled and first_entry is not None)


def _earliest(current: datetime | None, entries: list[datetime]) -> datetime | None:
    return min([*entries, *([current] if current is not None else [])], default=None)
