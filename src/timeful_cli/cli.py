"""Command-line interface for timeful-cli."""

from __future__ import annotations

import argparse
import getpass
import json
import re
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone
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
        description="Unofficial CLI for Timeful events.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--anonymous", action="store_true", help="Ignore any saved login for this command.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help=argparse.SUPPRESS)
    parser.add_argument("--timeout", type=float, default=30, help=argparse.SUPPRESS)
    commands = parser.add_subparsers(dest="command", required=True)

    auth = commands.add_parser("auth", help="Log in, check status, or log out.")
    auth_commands = auth.add_subparsers(dest="auth_command", required=True)
    login = auth_commands.add_parser("login", help="Log in securely with an email OTP.")
    login.add_argument("--email", help="Timeful account email. Prompted when omitted.")
    login.add_argument("--first-name", help="Required when creating a new Timeful account.")
    login.add_argument("--last-name", help="Optional surname for a new Timeful account.")
    auth_commands.add_parser("status", help="Check whether the saved session is authenticated.")
    auth_commands.add_parser("logout", help="Sign out and remove the saved session.")

    create = commands.add_parser("create", help="Create an event, owned when logged in.")
    create.add_argument("--name", help="Event name.")
    create.add_argument("--duration", type=parse_duration, default=1.0, help="Meeting length, e.g. 30m or 1h.")
    create.add_argument("--date", action="append", type=iso_timestamp, help="Candidate ISO timestamp. Repeat as needed.")
    create.add_argument("--type", choices=("specific_dates", "dow"), default="specific_dates")
    create.add_argument("--increment", type=int, choices=(15, 30, 60), default=15, help="Slot size in minutes.")
    create.add_argument("--days-only", action="store_true", help="Poll for whole days.")
    create.add_argument("--collect-emails", action="store_true", help="Ask guests for email addresses.")
    create.add_argument("--blind", action="store_true", help="Only the authenticated owner can see all responses.")
    create.add_argument("--payload-file", metavar="PATH", help="Use a complete JSON request body instead.")
    create.add_argument("--url-only", action="store_true", help="Print only the share URL.")

    show = commands.add_parser("show", help="Read a public event.")
    show.add_argument("event_id", help="Long ID, short ID, or share URL.")

    results = commands.add_parser("results", help="Show names and availability in one result.")
    results.add_argument("event_id", help="Long ID, short ID, or share URL.")
    results.add_argument("--time-min", type=iso_timestamp, help="Override the event's earliest timestamp.")
    results.add_argument("--time-max", type=iso_timestamp, help="Override the event's latest timestamp.")

    responses = commands.add_parser("responses", help="Read raw public event responses.")
    responses.add_argument("event_id", help="Long ID, short ID, or share URL.")
    responses.add_argument("--time-min", required=True, type=iso_timestamp)
    responses.add_argument("--time-max", required=True, type=iso_timestamp)
    responses.add_argument("--guest-name", help="Guest name for blind-availability events.")

    respond = commands.add_parser("respond", help="Set availability as yourself or a guest.")
    respond.add_argument("event_id", help="Long ID, short ID, or share URL.")
    identity = respond.add_mutually_exclusive_group(required=True)
    identity.add_argument("--as-me", action="store_true", help="Respond using the authenticated account.")
    identity.add_argument("--name", help="Respond as a guest with this name.")
    respond.add_argument("--email", help="Required when the event collects guest emails.")
    respond.add_argument("--available", action="append", type=iso_timestamp, default=[], metavar="TIME")
    respond.add_argument("--if-needed", action="append", type=iso_timestamp, default=[], metavar="TIME")
    return parser


def normalize_event_id(value: str) -> str:
    parsed = urllib.parse.urlparse(value)
    path = parsed.path if parsed.scheme and parsed.netloc else value
    return path.rstrip("/").rsplit("/", 1)[-1]


def _parse_event_date(value: Any) -> datetime:
    if not isinstance(value, str):
        raise TimefulError("Timeful returned an event date in an unsupported format.")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def event_time_bounds(event: dict[str, Any]) -> tuple[str, str]:
    dates = event.get("dates") or []
    if not dates:
        raise TimefulError("This event has no dates; provide --time-min and --time-max.")
    parsed = [_parse_event_date(value) for value in dates]
    time_min = min(parsed)
    time_max = max(parsed) + timedelta(days=1)
    return (
        time_min.isoformat().replace("+00:00", "Z"),
        time_max.isoformat().replace("+00:00", "Z"),
    )


def merge_results(event: dict[str, Any], responses: dict[str, Any], event_id: str) -> dict[str, Any]:
    metadata = event.get("responses") or {}
    if not isinstance(metadata, dict):
        raise TimefulError("Timeful returned unexpected response metadata.")
    respondents: list[dict[str, Any]] = []
    for response_id, response in responses.items():
        response = response or {}
        if not isinstance(response, dict):
            raise TimefulError("Timeful returned an unexpected respondent payload.")
        details = metadata.get(response_id) or {}
        if not isinstance(details, dict):
            raise TimefulError("Timeful returned unexpected respondent metadata.")
        user = details.get("user") or response.get("user") or {}
        if not isinstance(user, dict):
            raise TimefulError("Timeful returned unexpected user metadata.")
        full_name = " ".join(part for part in (user.get("firstName"), user.get("lastName")) if part).strip()
        name = response.get("name") or details.get("name") or full_name or response_id
        email = response.get("email") or details.get("email") or user.get("email")
        respondent: dict[str, Any] = {
            "id": response_id,
            "name": name,
            "availability": response.get("availability") or [],
            "ifNeeded": response.get("ifNeeded") or [],
        }
        if email:
            respondent["email"] = email
        if response.get("manualAvailability"):
            respondent["manualAvailability"] = response["manualAvailability"]
        respondents.append(respondent)

    respondents.sort(key=lambda item: (item["name"].casefold(), item["id"]))
    return {
        "event": {
            "id": event.get("_id") or event_id,
            "shortId": event.get("shortId"),
            "name": event.get("name"),
            "blind": bool(event.get("blindAvailabilityEnabled")),
            "collectEmails": bool(event.get("collectEmails")),
        },
        "responseCount": len(respondents),
        "respondents": respondents,
    }


def local_timezone_offset() -> int:
    offset = datetime.now().astimezone().utcoffset() or timedelta()
    return -int(offset.total_seconds() // 60)


def login(client: TimefulClient, args: argparse.Namespace) -> dict[str, Any]:
    email = (args.email or input("Email: ")).strip().lower()
    if "@" not in email:
        raise TimefulError("Enter a valid email address.")

    is_new_user = client.check_email(email)
    first_name = (args.first_name or "").strip()
    last_name = (args.last_name or "").strip()
    if is_new_user and not first_name:
        first_name = input("First name: ").strip()
        if not first_name:
            raise TimefulError("First name is required for a new Timeful account.")
        if args.last_name is None:
            last_name = input("Last name (optional): ").strip()

    client.send_otp(email)
    print(f"Timeful sent a six-digit code to {email}.", file=sys.stderr)
    code = getpass.getpass("OTP code: ").strip()
    if not re.fullmatch(r"\d{6}", code):
        raise TimefulError("The OTP must be exactly six digits.")

    user = client.verify_otp(
        email,
        code,
        timezone_offset=local_timezone_offset(),
        first_name=first_name,
        last_name=last_name,
    )
    name = " ".join(part for part in (user.get("firstName"), user.get("lastName")) if part).strip()
    return {"authenticated": True, "email": user.get("email", email), "name": name}


def run(args: argparse.Namespace) -> Any:
    if args.command == "auth" and args.anonymous:
        raise TimefulError("--anonymous cannot be used with auth commands.")
    client = TimefulClient(
        base_url=args.base_url,
        timeout=args.timeout,
        use_stored_session=not args.anonymous,
    )
    if args.command == "auth":
        if args.auth_command == "login":
            return login(client, args)
        if args.auth_command == "status":
            return {"authenticated": client.auth_status()}
        if args.auth_command == "logout":
            client.sign_out()
            return {"authenticated": False}
    if args.command == "create":
        payload = create_payload(args)
        if payload.get("blindAvailabilityEnabled") and not client.auth_status():
            raise TimefulError("Log in before creating a blind event so you can view its responses.")
        result = client.create_event(payload)
        if args.url_only:
            if not result.get("url"):
                raise TimefulError("Timeful did not return a share URL.")
            return result["url"]
        return result
    if args.command == "show":
        return client.get_event(normalize_event_id(args.event_id))
    if args.command == "results":
        if bool(args.time_min) != bool(args.time_max):
            raise TimefulError("Provide both --time-min and --time-max, or omit both.")
        event_id = normalize_event_id(args.event_id)
        event = client.get_event(event_id)
        if not isinstance(event, dict):
            raise TimefulError("Timeful returned an unexpected event response.")
        time_min, time_max = (args.time_min, args.time_max) if args.time_min else event_time_bounds(event)
        responses = client.get_responses(event_id, time_min=time_min, time_max=time_max)
        if not isinstance(responses, dict):
            raise TimefulError("Timeful returned an unexpected responses payload.")
        return merge_results(event, responses, event_id)
    if args.command == "responses":
        return client.get_responses(
            normalize_event_id(args.event_id),
            time_min=args.time_min,
            time_max=args.time_max,
            guest_name=args.guest_name,
        )
    if args.command == "respond":
        if args.as_me and not client.auth_status():
            raise TimefulError("Log in before using --as-me.")
        if args.as_me and args.email:
            raise TimefulError("--email is only valid for guest responses using --name.")
        if not args.as_me and not (args.name or "").strip():
            raise TimefulError("Guest name cannot be empty.")
        return client.set_response(
            normalize_event_id(args.event_id),
            name=args.name or "",
            email=args.email,
            availability=args.available,
            if_needed=args.if_needed,
            as_guest=not args.as_me,
        )
    raise TimefulError(f"Unknown command: {args.command}")


def main(argv: Sequence[str] | None = None) -> None:
    try:
        result = run(build_parser().parse_args(argv))
    except EOFError:
        print("\ntimeful: login cancelled.", file=sys.stderr)
        raise SystemExit(130) from None
    except KeyboardInterrupt:
        print("\ntimeful: cancelled.", file=sys.stderr)
        raise SystemExit(130) from None
    except TimefulError as exc:
        print(f"timeful: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    if isinstance(result, str):
        print(result)
    else:
        json.dump(result, sys.stdout, indent=2, sort_keys=True)
        print()
