import argparse
import sys
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session

from stock_radar.db.config import database_url
from stock_radar.db.models import CollectionRun, Instrument, SignalObservation, TrackingRun
from stock_radar.services.collections import eligible_expression

EXIT_ABORTED = 1


class PruneAborted(Exception):
    pass


@dataclass(frozen=True)
class PruneRequest:
    collection_id: UUID
    expected_total: int
    expected_eligible: int
    expected_symbols: frozenset[str]
    apply: bool


@dataclass(frozen=True)
class PruneResult:
    total: int
    eligible: int
    removed: int
    preserved_tracking_runs: int
    applied: bool


def prune(session: Session, request: PruneRequest) -> PruneResult:
    try:
        result = inspect_and_remove(session, request)
    except BaseException:
        session.rollback()
        raise
    if result.applied:
        session.commit()
    else:
        session.rollback()
    return result


def inspect_and_remove(session: Session, request: PruneRequest) -> PruneResult:
    collection = session.scalar(select(CollectionRun).where(CollectionRun.id == request.collection_id).with_for_update())
    if collection is None:
        raise PruneAborted("collection not found")
    in_collection = SignalObservation.collection_run_id == request.collection_id
    eligible_rows = select(SignalObservation.id).where(in_collection, eligible_expression())
    ineligible_rows = select(SignalObservation.id).where(in_collection, eligible_expression().is_not(True))
    total = session.scalar(select(func.count(SignalObservation.id)).where(in_collection))
    eligible = session.scalar(select(func.count()).select_from(eligible_rows.subquery()))
    eligible_symbols = frozenset(session.scalars(
        select(Instrument.symbol).join(SignalObservation, SignalObservation.instrument_id == Instrument.id).where(in_collection, eligible_expression())
    ))
    print(f"Observed: {total} observations, {eligible} eligible, symbols {sorted(eligible_symbols)}.")
    divergences = []
    if total != request.expected_total:
        divergences.append(f"expected {request.expected_total} observations, found {total}")
    if eligible != request.expected_eligible:
        divergences.append(f"expected {request.expected_eligible} eligible, found {eligible}")
    if eligible_symbols != request.expected_symbols:
        divergences.append(f"expected eligible symbols {sorted(request.expected_symbols)}, found {sorted(eligible_symbols)}")
    if collection.rows_examined is not None:
        divergences.append("the collection already records rows_examined, so it is not a legacy collection")
    blocked = session.scalar(select(func.count(TrackingRun.id)).where(TrackingRun.signal_observation_id.in_(ineligible_rows)))
    if blocked:
        divergences.append(f"{blocked} tracking runs reference observations that would be removed")
    if divergences:
        raise PruneAborted("; ".join(divergences))
    preserved = session.scalar(select(func.count(TrackingRun.id)).where(TrackingRun.signal_observation_id.in_(eligible_rows)))
    removable = total - eligible
    print(f"Plan: remove {removable} observations, keep {eligible} with {preserved} tracking runs, record rows_examined={total}.")
    if not request.apply:
        return PruneResult(total, eligible, 0, preserved, False)
    removed = session.execute(delete(SignalObservation).where(SignalObservation.id.in_(ineligible_rows))).rowcount
    collection.rows_examined = total
    session.flush()
    remaining = session.scalar(select(func.count(SignalObservation.id)).where(in_collection))
    if removed != removable or remaining != eligible:
        raise PruneAborted(f"removed {removed} and kept {remaining}, which differs from the plan")
    return PruneResult(total, eligible, removed, preserved, True)


def parse_arguments(arguments: list[str]) -> PruneRequest:
    parser = argparse.ArgumentParser(prog="python -m stock_radar.db.prune_collection")
    parser.add_argument("--collection-id", type=UUID, required=True)
    parser.add_argument("--expected-total", type=int, required=True)
    parser.add_argument("--expected-eligible", type=int, required=True)
    parser.add_argument("--expected-symbols", required=True)
    parser.add_argument("--apply", action="store_true")
    parsed = parser.parse_args(arguments)
    symbols = frozenset(symbol.strip() for symbol in parsed.expected_symbols.split(",") if symbol.strip())
    return PruneRequest(parsed.collection_id, parsed.expected_total, parsed.expected_eligible, symbols, parsed.apply)


def main(arguments: list[str]) -> int:
    request = parse_arguments(arguments)
    engine = create_engine(database_url(), hide_parameters=True)
    try:
        with Session(engine) as session:
            result = prune(session, request)
    except PruneAborted as error:
        print(f"Aborted, nothing changed: {error}.", file=sys.stderr)
        return EXIT_ABORTED
    finally:
        engine.dispose()
    if result.applied:
        print(f"Applied: removed {result.removed} observations from collection {request.collection_id}.")
    else:
        print("Dry run, nothing changed. Repeat with --apply to remove them.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
