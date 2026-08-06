from __future__ import annotations

import argparse
import json
import sys
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from typing import Sequence, TextIO


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _bounded_integer(
    *,
    minimum: int,
    maximum: int,
):
    def parse(value: str) -> int:
        number = int(value)
        if not minimum <= number <= maximum:
            raise argparse.ArgumentTypeError(
                f"must be between {minimum} and {maximum}"
            )
        return number

    return parse


def _parse_now(
    value: str | None,
) -> datetime | None:
    if value is None:
        return None
    clean = value.strip()
    if clean.endswith("Z"):
        clean = clean[:-1] + "+00:00"
    parsed = datetime.fromisoformat(clean)
    if parsed.tzinfo is None:
        raise ValueError(
            "--now must include a UTC offset."
        )
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Count MARK-OS structured application errors from "
            "newline-delimited Railway JSON logs."
        )
    )
    parser.add_argument(
        "--input",
        default="-",
        help=(
            "NDJSON file path, or - for standard input "
            "(default)."
        ),
    )
    parser.add_argument(
        "--hours",
        type=_bounded_integer(
            minimum=1,
            maximum=24 * 31,
        ),
        default=24,
    )
    parser.add_argument(
        "--max-samples",
        type=_bounded_integer(
            minimum=0,
            maximum=100,
        ),
        default=20,
    )
    parser.add_argument(
        "--now",
        help=(
            "Optional timezone-aware ISO timestamp for deterministic "
            "review or testing."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print a machine-readable summary.",
    )
    parser.add_argument(
        "--fail-on-errors",
        action="store_true",
        help=(
            "Return status 1 when at least one error is found."
        ),
    )
    return parser


def _input_stream(
    value: str,
):
    if value == "-":
        return nullcontext(sys.stdin)
    path = Path(value).expanduser().resolve()
    return path.open(
        "r",
        encoding="utf-8",
    )


def _print_text(
    summary,
    stream: TextIO,
) -> None:
    print(
        f"MARK-OS errors in previous {summary.hours} hours: "
        f"{summary.error_count}",
        file=stream,
    )
    print(
        "Window: "
        f"{summary.window_start_utc} to "
        f"{summary.window_end_utc}",
        file=stream,
    )
    print(
        "Unique correlation IDs: "
        f"{summary.unique_correlation_ids}",
        file=stream,
    )
    print(
        "Input lines: "
        f"{summary.source_lines}; malformed: "
        f"{summary.malformed_lines}; ignored: "
        f"{summary.ignored_lines}; outside window: "
        f"{summary.out_of_window_lines}",
        file=stream,
    )

    if summary.by_event:
        print("Errors by event:", file=stream)
        for event, count in summary.by_event.items():
            print(
                f"  {event}: {count}",
                file=stream,
            )
    else:
        print(
            "No MARK-OS application errors were found.",
            file=stream,
        )

    if summary.samples:
        print("Recent safe samples:", file=stream)
        for sample in summary.samples:
            details = [
                sample.timestamp,
                sample.event,
            ]
            if sample.correlation_id:
                details.append(
                    f"request={sample.correlation_id}"
                )
            if sample.path:
                details.append(
                    f"path={sample.path}"
                )
            if sample.status_code is not None:
                details.append(
                    f"status={sample.status_code}"
                )
            if sample.exception_type:
                details.append(
                    f"exception={sample.exception_type}"
                )
            print(
                "  " + " | ".join(details),
                file=stream,
            )


def main(
    argv: Sequence[str] | None = None,
) -> int:
    from app.services.error_summary import (
        summarize_error_lines,
    )

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        now_utc = _parse_now(args.now)
        with _input_stream(args.input) as stream:
            summary = summarize_error_lines(
                stream,
                now_utc=now_utc,
                hours=args.hours,
                max_samples=args.max_samples,
            )
    except (
        OSError,
        UnicodeError,
        ValueError,
    ) as exc:
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )
        return 2

    if args.json:
        print(
            json.dumps(
                summary.as_dict(),
                indent=2,
                sort_keys=True,
            )
        )
    else:
        _print_text(
            summary,
            sys.stdout,
        )

    if (
        args.fail_on_errors
        and summary.error_count > 0
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
