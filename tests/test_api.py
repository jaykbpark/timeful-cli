import http.cookiejar
import io
import stat
import tempfile
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock

from timeful_cli.api import TimefulClient, TimefulError


def json_response(payload: bytes) -> MagicMock:
    response = MagicMock()
    response.read.return_value = payload
    response.__enter__.return_value = response
    return response


def session_cookie() -> http.cookiejar.Cookie:
    return http.cookiejar.Cookie(
        version=0,
        name="session",
        value="test-session",
        port=None,
        port_specified=False,
        domain="timeful.app",
        domain_specified=True,
        domain_initial_dot=False,
        path="/",
        path_specified=True,
        secure=True,
        expires=None,
        discard=True,
        comment=None,
        comment_url=None,
        rest={"HttpOnly": None},
        rfc2109=False,
    )


class AuthHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        if self.path == "/api/auth/otp/verify":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Set-Cookie", "session=round-trip; Path=/; HttpOnly")
            self.end_headers()
            self.wfile.write(b'{"email":"jay@example.com"}')
            return
        self.send_error(404)

    def do_GET(self) -> None:
        if self.path == "/api/auth/status" and "session=round-trip" in self.headers.get("Cookie", ""):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"{}")
            return
        self.send_error(401)


class ApiTests(unittest.TestCase):
    def test_create_event_adds_share_url(self) -> None:
        opener = MagicMock()
        opener.open.return_value = json_response(b'{"shortId":"abc123"}')
        client = TimefulClient(use_stored_session=False, opener=opener)

        event = client.create_event({"name": "Coffee", "type": "specific_dates"})

        self.assertEqual(event["url"], "https://timeful.app/e/abc123")
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")

    def test_http_error_is_friendly(self) -> None:
        opener = MagicMock()
        opener.open.side_effect = urllib.error.HTTPError(
            "https://timeful.app/api/events", 400, "Bad Request", {}, io.BytesIO(b"invalid event")
        )
        with self.assertRaisesRegex(TimefulError, "HTTP 400"):
            TimefulClient(use_stored_session=False, opener=opener).create_event({})

    def test_saved_session_uses_restricted_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cookie_path = Path(directory) / "config" / "cookies.txt"
            client = TimefulClient(cookie_path=cookie_path, opener=MagicMock())
            client.cookie_jar.set_cookie(session_cookie())

            client._save_session()

            self.assertEqual(stat.S_IMODE(cookie_path.stat().st_mode), 0o600)
            restored = TimefulClient(cookie_path=cookie_path, opener=MagicMock())
            self.assertEqual([(cookie.name, cookie.value) for cookie in restored.cookie_jar], [("session", "test-session")])

    def test_login_cookie_round_trip(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), AuthHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        with tempfile.TemporaryDirectory() as directory:
            cookie_path = Path(directory) / "cookies.txt"
            base_url = f"http://127.0.0.1:{server.server_port}"
            client = TimefulClient(base_url=base_url, cookie_path=cookie_path)
            client.verify_otp("jay@example.com", "123456", timezone_offset=0)

            restored = TimefulClient(base_url=base_url, cookie_path=cookie_path)
            self.assertTrue(restored.auth_status())
            self.assertEqual(stat.S_IMODE(cookie_path.stat().st_mode), 0o600)

    def test_auth_status_skips_network_without_saved_cookie(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            opener = MagicMock()
            client = TimefulClient(cookie_path=Path(directory) / "cookies.txt", opener=opener)
            self.assertFalse(client.auth_status())
            opener.open.assert_not_called()

    def test_auth_status_removes_a_rejected_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cookie_path = Path(directory) / "cookies.txt"
            opener = MagicMock()
            client = TimefulClient(cookie_path=cookie_path, opener=opener)
            client.cookie_jar.set_cookie(session_cookie())
            client._save_session()
            opener.open.side_effect = urllib.error.HTTPError(
                "https://timeful.app/api/auth/status", 401, "Unauthorized", {}, io.BytesIO(b"{}")
            )

            self.assertFalse(client.auth_status())
            self.assertFalse(cookie_path.exists())

    def test_authenticated_response_does_not_send_guest_identity(self) -> None:
        opener = MagicMock()
        opener.open.return_value = json_response(b"{}")
        client = TimefulClient(use_stored_session=False, opener=opener)

        client.set_response("event", availability=[], if_needed=[], as_guest=False)

        request = opener.open.call_args.args[0]
        self.assertEqual(request.data, b'{"guest": false, "availability": [], "ifNeeded": []}')


if __name__ == "__main__":
    unittest.main()
