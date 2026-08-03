"""Command-line interface for timeful-cli."""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from . import __version__
from .api import DEFAULT_BASE_URL, TimefulClient, TimefulError


def parse_duration(value: str) -> float:
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(m|min|h|hr)?\s*", value, re.IGNORECASE)
    if not match:
        raise argparse.ArgumentTypeError("Use minutes or hours, such as 30m, 1h, or 1.5h.")
    amount = float(match.group(1))
    if amount <= 0:
        raise argparse.ArgumentTypeError("Duration must be greater than zero.")
    return amount / 60 if (match.group(2) or "h").lower() in {"m", "min"} else amount


def iso_timestamp(value: str) -> str:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Not a valid ISO timestamp: {value}") from exc
    return value


def load_payload(path: str) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise TimefulError(f"Could not read payload file: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise TimefulError(f"Payload file is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise TimefulError("Payload file must contain one JSON object.")
    return payload


def create_payload(args: argparse.Namespace) -> dict[str, Any]:
    if args.payload_file:
        return load_payload(args.payload_file)
    if not args.name:
        raise TimefulError("--name is required unless --payload-file is used.")
    if not args.date:
        raise TimefulError("At least one --date is required unless --payload-file is used.")
    return {
        "name": args.name,
        "duration": args.duration,
        "dates": args.date,
        "type": args.type,
        "timeIncrement": args.increment,
        "notificationsEnabled": False,
        "blindAvailabilityEnabled": args.blind,
        "daysOnly": args.days_only,
        "sendEmailAfterXResponses": -1,
        "collectEmails": args.collect_emails,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="timeful",
        description="Unofficial CLI for public Timeful events.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help=argparse.SUPPRESS)
    parser.add_argument("--timeout", type=float, default=30, help=argparse.SUPPRESS)
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create", help="Create an anonymous event.")
    create.add_argument("--name", help="Event name.")
    create.add_argument("--duration", type=parse_duration, default=1.0, help="Meeting length, e.g. 30m or 1h.")
    create.add_argument("--date", action="append", type=iso_timestamp, help="Candidate ISO timestamp. Repeat as needed.")
    create.add_argument("--type", choices=("specific_dates", "dow"), default="specific_dates")
    create.add_argument("--increment", type=int, choices=(15, 30, 60), default=15, help="Slot size in minutes.")
    create.add_argument("--days-only", action="store_true", help="Poll for whole days.")
    create.add_argument("--collect-emails", action="store_true", help="Ask guests for email addresses.")
    create.add_argument("--blind", action="store_true", help="Hide responses from other guests.")
    create.add_argument("--payload-file", metavar="PATH", help="Use a complete JSON request body instead.")
    create.add_argument("--url-only", action="store_true", help="Print only the share URL.")

    show = commands.add_parser("show", help="Read a public event.")
    show.add_argument("event_id", help="Long ID, short ID, or share URL.")

    responses = commands.add_parser("responses", help="Read public event responses.")
    responses.add_argument("event_id", help="Long ID, short ID, or share URL.")
    responses.add_argument("--time-min", required=True, type=iso_timestamp)
    responses.add_argument("--time-max", required=True, type=iso_timestamp)
    responses.add_argument("--guest-name", help="Guest name for blind-availability events.")

    respond = commands.add_parser("respond", help="Set guest availability.")
    respond.add_argument("event_id", help="Long ID, short ID, or share URL.")
    respond.add_argument("--name", required=True, help="Guest name.")
    respond.add_argument("--email", help="Required when the event collects emails.")
    respond.add_argument("--available", action="append", type=iso_timestamp, default=[], metavar="TIME")
    respond.add_argument("--if-needed", action="append", type=iso_timestamp, default=[], metavar="TIME")
    return parser


def normalize_event_id(value: str) -> str:
    parsed = urllib.parse.urlparse(value)
    path = parsed.path if parsed.scheme and parsed.netloc else value
    return path.rstrip("/").rsplit("/", 1)[-1]


def run(args: argparse.Namespace) -> Any:
    client = TimefulClient(base_url=args.base_url, timeout=args.timeout)
    if args.command == "create":
        result = client.create_event(create_payload(args))
        if args.url_only:
            if not result.get("url"):
                raise TimefulError("Timeful did not return a share URL.")
            return result["url"]
        return result
    if args.command == "show":
        return client.get_event(normalize_event_id(args.event_id))
    if args.command == "responses":
        return client.get_responses(
            normalize_event_id(args.event_id),
            time_min=args.time_min,
            time_max=args.time_max,
            guest_name=args.guest_name,
        )
    if args.command == "respond":
        return client.set_guest_response(
            normalize_event_id(args.event_id),
            name=args.name,
            email=args.email,
            availability=args.available,
            if_needed=args.if_needed,
        )
    raise TimefulError(f"Unknown command: {args.command}")


def main(argv: Sequence[str] | None = None) -> None:
    try:
        result = run(build_parser().parse_args(argv))
    except TimefulError as exc:
        print(f"timeful: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    if isinstance(result, str):
        print(result)
    else:
        json.dump(result, sys.stdout, indent=2, sort_keys=True)
        print()
