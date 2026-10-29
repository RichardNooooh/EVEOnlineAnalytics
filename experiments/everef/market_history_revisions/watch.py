from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from datetime import UTC, date, datetime, timedelta
from http.client import HTTPException
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

if TYPE_CHECKING:
    from collections.abc import Callable


def _utc_now(now: datetime | None) -> datetime:
    value = now or datetime.now(UTC)
    if value.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return value.astimezone(UTC)


def _timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _parse_market_date(value: str) -> str:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("market date must be YYYY-MM-DD") from error
    if parsed.isoformat() != value:
        raise ValueError("market date must be YYYY-MM-DD")
    return value


class TotalsValidationError(ValueError):
    def __init__(self, message: str, totals_path: str) -> None:
        super().__init__(message)
        self.totals_path = totals_path


def _write_state(evidence_dir: Path, state: dict[str, Any]) -> None:
    handle, temporary_name = tempfile.mkstemp(dir=evidence_dir, prefix=".state-", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as temporary:
            json.dump(state, temporary, indent=2)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        Path(temporary_name).replace(evidence_dir / "state.json")
    finally:
        Path(temporary_name).unlink(missing_ok=True)


def _available_path(evidence_dir: Path, stem: str, suffix: str) -> Path:
    candidate = evidence_dir / f"{stem}{suffix}"
    number = 2
    while candidate.exists():
        candidate = evidence_dir / f"{stem}-{number}{suffix}"
        number += 1
    return candidate


def _download_totals(evidence_dir: Path, url: str, observed_at: datetime, market_date: str) -> tuple[str, int | None]:
    with urlopen(Request(url, method="GET"), timeout=30) as response:
        payload = response.read()
    decoded = json.loads(payload)
    destination = _available_path(evidence_dir, f"totals-{_timestamp(observed_at).replace(':', '-')}", ".json")
    destination.write_bytes(payload)
    if not isinstance(decoded, dict):
        raise TotalsValidationError("totals JSON must be an object", destination.name)
    count = decoded.get(market_date)
    if count is not None and (not isinstance(count, int) or isinstance(count, bool) or count < 0):
        raise TotalsValidationError(f"totals count for {market_date} must be a non-negative integer", destination.name)
    return destination.name, count


def _last_successful_observation(state: dict[str, Any]) -> dict[str, Any] | None:
    for observation in reversed(state["observations"]):
        if observation["status"] in {"downloaded", "unchanged"}:
            return observation
    return None


def _record(state: dict[str, Any], observation: dict[str, Any]) -> None:
    cast("list[dict[str, Any]]", state["observations"]).append(observation)


def _download_archive(evidence_dir: Path, url: str, market_date: str, observed_at: datetime) -> str:
    destination = _available_path(
        evidence_dir, f"market-history-{market_date}-{_timestamp(observed_at).replace(':', '-')}", ".csv.bz2"
    )
    handle, temporary_name = tempfile.mkstemp(dir=evidence_dir, prefix=".archive-", suffix=".tmp")
    written = 0
    try:
        with os.fdopen(handle, "wb") as temporary, urlopen(Request(url, method="GET"), timeout=30) as response:
            expected = response.headers.get("Content-Length")
            while chunk := response.read(1024 * 1024):
                temporary.write(chunk)
                written += len(chunk)
            if expected is not None:
                try:
                    expected_size = int(expected)
                except ValueError as error:
                    raise OSError(f"malformed Content-Length: {expected}") from error
                if written != expected_size:
                    raise OSError(f"truncated archive: expected {expected} bytes, received {written}")
            temporary.flush()
            os.fsync(temporary.fileno())
        Path(temporary_name).replace(destination)
    finally:
        Path(temporary_name).unlink(missing_ok=True)
    return destination.name


def run_poll(
    evidence_dir: Path,
    *,
    now: datetime | None = None,
    clock: Callable[[], datetime] | None = None,
    base_url: str = "https://data.everef.net",
) -> dict[str, object]:
    """Record one observation; ``now`` and ``clock`` provide deterministic test time."""
    observed_at = _utc_now(now)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    state_path = evidence_dir / "state.json"
    if state_path.exists():
        state: dict[str, Any] = json.loads(state_path.read_text(encoding="utf-8"))
    else:
        state = {
            "schema_version": 1,
            "market_date": observed_at.date().isoformat(),
            "baseline_at": None,
            "deadline_at": None,
            "observations": [],
        }
        _write_state(evidence_dir, state)

    deadline_at = cast("str | None", state["deadline_at"])
    if deadline_at is not None and observed_at >= _parse_timestamp(deadline_at):
        return {"status": "deadline_reached", "market_date": state["market_date"]}
    observations = cast("list[dict[str, Any]]", state["observations"])
    if observations and observed_at < _parse_timestamp(cast("str", observations[-1]["observed_at"])) + timedelta(
        hours=1
    ):
        return {"status": "not_due", "market_date": state["market_date"]}

    market_date = str(state["market_date"])
    try:
        totals_path, totals_count = _download_totals(
            evidence_dir, f"{base_url}/market-history/totals.json", observed_at, market_date
        )
    except (HTTPError, HTTPException, URLError, OSError, ValueError, json.JSONDecodeError) as error:
        observation: dict[str, Any] = {
            "observed_at": _timestamp(observed_at),
            "status": "error",
            "archive_metadata": None,
            "totals_path": getattr(error, "totals_path", None),
            "totals_count": None,
            "archive_path": None,
            "error": str(error),
        }
        _record(state, observation)
        _write_state(evidence_dir, state)
        return observation
    archive_url = f"{base_url}/market-history/{market_date[:4]}/market-history-{market_date}.csv.bz2"
    metadata: dict[str, str | None] | None = None
    archive_path: str | None = None
    try:
        with urlopen(Request(archive_url, method="HEAD"), timeout=30) as response:
            metadata = {
                "etag": response.headers.get("ETag"),
                "last_modified": response.headers.get("Last-Modified"),
                "content_length": response.headers.get("Content-Length"),
            }
        previous = _last_successful_observation(state)
        metadata_changed = (
            previous is None
            or previous["archive_metadata"] != metadata
            or previous["totals_count"] != totals_count
            or not any(value is not None for value in metadata.values())
        )
        if metadata_changed:
            archive_path = _download_archive(evidence_dir, archive_url, market_date, observed_at)
            status = "downloaded"
            if state["baseline_at"] is None:
                completed_at = _utc_now(clock()) if clock else (observed_at if now is not None else datetime.now(UTC))
                state["baseline_at"] = _timestamp(completed_at)
                state["deadline_at"] = _timestamp(completed_at + timedelta(days=7))
        else:
            status = "unchanged"
            archive_path = previous["archive_path"]
    except HTTPError as error:
        if error.code == 404:
            status = "missing"
        else:
            status = "error"
            error_message = str(error)
    except (HTTPException, URLError, OSError) as error:
        status = "error"
        error_message = str(error)

    observation: dict[str, Any] = {
        "observed_at": _timestamp(observed_at),
        "status": status,
        "archive_metadata": metadata,
        "totals_path": totals_path,
        "totals_count": totals_count,
        "archive_path": archive_path if status == "downloaded" else None,
    }
    if status == "unchanged":
        observation["archive_path"] = archive_path
    if status == "error":
        observation["error"] = error_message
    _record(state, observation)
    _write_state(evidence_dir, state)
    return observation


def main() -> None:
    parser = argparse.ArgumentParser(description="Watch everef market-history archive revisions.")
    parser.add_argument("--once", action="store_true", help="Run one poll and exit.")
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / ".local" / "everef-market-history-revisions",
    )
    parser.add_argument("--date", help="Market date (YYYY-MM-DD) for a new evidence directory.")
    args = parser.parse_args()

    state_path = args.evidence_dir / "state.json"
    if args.date:
        try:
            _parse_market_date(args.date)
        except ValueError:
            parser.error("--date must be YYYY-MM-DD")
        if state_path.exists():
            persisted = json.loads(state_path.read_text(encoding="utf-8")).get("market_date")
            if persisted != args.date:
                parser.error(f"--date {args.date} conflicts with persisted market date {persisted}")
        else:
            args.evidence_dir.mkdir(parents=True, exist_ok=True)
            _write_state(
                args.evidence_dir,
                {
                    "schema_version": 1,
                    "market_date": args.date,
                    "baseline_at": None,
                    "deadline_at": None,
                    "observations": [],
                },
            )
    try:
        while True:
            result = run_poll(args.evidence_dir)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            observations = cast("list[dict[str, Any]]", state["observations"])
            error = ""
            if result["status"] == "error" and observations:
                error = f" {observations[-1].get('error', '')}"
            print(f"{_timestamp(datetime.now(UTC))} {state['market_date']} {result['status']}{error}".rstrip())
            if args.once or result["status"] == "deadline_reached":
                return
            delay = 3600.0
            if observations:
                next_poll = _parse_timestamp(cast("str", observations[-1]["observed_at"])) + timedelta(hours=1)
                delay = max(0.0, (next_poll - datetime.now(UTC)).total_seconds())
            if state["deadline_at"] is not None:
                delay = min(
                    delay,
                    max(0.0, (_parse_timestamp(cast("str", state["deadline_at"])) - datetime.now(UTC)).total_seconds()),
                )
            time.sleep(delay)
    except KeyboardInterrupt:
        print("stopped")
        return


if __name__ == "__main__":
    main()
