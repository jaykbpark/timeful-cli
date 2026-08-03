import argparse
import json
import tempfile
import unittest
from pathlib import Path

from timeful_cli.cli import build_parser, create_payload, normalize_event_id, parse_duration


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


if __name__ == "__main__":
    unittest.main()
