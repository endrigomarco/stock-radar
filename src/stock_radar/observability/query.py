import argparse
from collections import deque
import json
import os
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", default=os.environ.get("ERROR_LOOKUP_ID", ""))
    parser.add_argument("--limit", type=int, default=30)
    args = parser.parse_args()
    if not 1 <= args.limit <= 1000:
        parser.error("limit must be between 1 and 1000")
    directory = Path(os.environ.get("LOG_DIRECTORY", "/var/log/stock-radar"))
    files = [directory / f"events.jsonl.{index}" for index in range(5, 0, -1)] + [directory / "events.jsonl"]
    events = deque(maxlen=args.limit)
    for path in files:
        try:
            with path.open() as stream:
                for line in stream:
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    matches = args.id in {event.get(key) for key in ("request_id", "error_id", "fingerprint", "receipt_id")} if args.id else event.get("level") in {"ERROR", "WARNING"}
                    if matches:
                        events.append(event)
        except FileNotFoundError:
            continue
    for event in events:
        print(json.dumps(event, indent=2))
    if not events:
        print("No matching events in retained logs.")


if __name__ == "__main__":
    main()
