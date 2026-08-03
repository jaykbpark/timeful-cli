import io
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from timeful_cli.api import TimefulClient, TimefulError


class ApiTests(unittest.TestCase):
    @patch("timeful_cli.api.urllib.request.urlopen")
    def test_create_event_adds_share_url(self, urlopen: MagicMock) -> None:
        response = MagicMock()
        response.read.return_value = b'{"shortId":"abc123"}'
        urlopen.return_value.__enter__.return_value = response

        event = TimefulClient().create_event({"name": "Coffee", "type": "specific_dates"})

        self.assertEqual(event["url"], "https://timeful.app/e/abc123")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")

    @patch("timeful_cli.api.urllib.request.urlopen")
    def test_http_error_is_friendly(self, urlopen: MagicMock) -> None:
        urlopen.side_effect = urllib.error.HTTPError(
            "https://timeful.app/api/events", 400, "Bad Request", {}, io.BytesIO(b"invalid event")
        )
        with self.assertRaisesRegex(TimefulError, "HTTP 400"):
            TimefulClient().create_event({})


if __name__ == "__main__":
    unittest.main()
