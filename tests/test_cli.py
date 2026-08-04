import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from timeful_cli.cli import (
    build_parser,
    create_payload,
    event_time_bounds,
    login,
    merge_results,
    normalize_event_id,
    parse_duration,
    run,
)
from timeful_cli.api import TimefulError


class CliTests(unittest.TestCase):
    def test_parse_duration(self) -> None:
        self.assertEqual(parse_duration("30m"), 0.5)
        self.assertEqual(parse_duration("1.5h"), 1.5)

    def test_normalize_event_id_accepts_url(self) -> None:
        self.assertEqual(normalize_event_id("https://timeful.app/e/abc123"), "abc123")
        self.assertEqual(normalize_event_id("https://timeful.app/e/abc123?source=chat"), "abc123")

    def test_create_payload_from_flags(self) -> None:
        args = build_parser().parse_args(
            ["create", "--name", "Coffee", "--duration", "30m", "--date", "2026-08-10T17:00:00Z"]
        )
        payload = create_payload(args)
        self.assertEqual(payload["name"], "Coffee")
        self.assertEqual(payload["duration"], 0.5)
        self.assertEqual(payload["timeIncrement"], 15)

    def test_payload_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "event.json"
            path.write_text(json.dumps({"name": "From JSON"}), encoding="utf-8")
            args = argparse.Namespace(payload_file=str(path))
            self.assertEqual(create_payload(args), {"name": "From JSON"})

    @patch("timeful_cli.cli.TimefulClient")
    def test_blind_payload_file_requires_login(self, client_class: MagicMock) -> None:
        client_class.return_value.auth_status.return_value = False
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "event.json"
            path.write_text(json.dumps({"name": "Blind", "blindAvailabilityEnabled": True}), encoding="utf-8")
            args = build_parser().parse_args(["create", "--payload-file", str(path)])
            with self.assertRaisesRegex(TimefulError, "Log in"):
                run(args)

    def test_event_time_bounds_cover_the_last_day(self) -> None:
        self.assertEqual(
            event_time_bounds({"dates": ["2026-08-10T00:00:00Z", "2026-08-12T00:00:00Z"]}),
            ("2026-08-10T00:00:00Z", "2026-08-13T00:00:00Z"),
        )

    def test_merge_results_resolves_signed_in_and_guest_names(self) -> None:
        event = {
            "_id": "long-id",
            "shortId": "short-id",
            "name": "Planning",
            "responses": {
                "user-id": {"user": {"firstName": "Ada", "lastName": "Lovelace", "email": "ada@example.com"}},
                "Grace": {"name": "Grace"},
            },
            "collectEmails": True,
        }
        responses = {
            "user-id": {"availability": ["2026-08-10T17:00:00Z"], "ifNeeded": []},
            "Grace": {"name": "Grace", "availability": [], "ifNeeded": ["2026-08-10T18:00:00Z"]},
        }

        result = merge_results(event, responses, "short-id")

        self.assertEqual(result["responseCount"], 2)
        self.assertEqual(result["respondents"][0]["name"], "Ada Lovelace")
        self.assertEqual(result["respondents"][0]["email"], "ada@example.com")
        self.assertEqual(result["respondents"][1]["name"], "Grace")

    @patch("timeful_cli.cli.getpass.getpass", return_value="123456")
    def test_login_sends_otp_and_returns_sanitized_identity(self, getpass_mock: MagicMock) -> None:
        client = MagicMock()
        client.check_email.return_value = False
        client.verify_otp.return_value = {
            "email": "jay@example.com",
            "firstName": "Jay",
            "lastName": "Park",
            "calendarAccounts": {"private": "not returned"},
        }
        args = argparse.Namespace(email="JAY@example.com", first_name=None, last_name=None)

        result = login(client, args)

        client.send_otp.assert_called_once_with("jay@example.com")
        client.verify_otp.assert_called_once()
        self.assertEqual(result, {"authenticated": True, "email": "jay@example.com", "name": "Jay Park"})
        self.assertNotIn("calendarAccounts", result)
        getpass_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
