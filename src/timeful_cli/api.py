"""Dependency-free client for Timeful's event and authentication endpoints."""

from __future__ import annotations

import http.cookiejar
import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from . import __version__


DEFAULT_BASE_URL = "https://timeful.app"


def default_config_dir() -> Path:
    configured = os.environ.get("TIMEFUL_CONFIG_DIR")
    if configured:
        return Path(configured).expanduser()
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config:
        return Path(xdg_config).expanduser() / "timeful-cli"
    return Path.home() / ".config" / "timeful-cli"


class TimefulError(RuntimeError):
    """A friendly error returned by Timeful or the network."""


class TimefulHTTPError(TimefulError):
    def __init__(self, status: int, reason: str, details: str = "") -> None:
        self.status = status
        self.reason = reason
        self.details = details
        suffix = f"\n{details}" if details else ""
        super().__init__(f"Timeful returned HTTP {status} {reason}.{suffix}")


class TimefulClient:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30,
        *,
        use_stored_session: bool = True,
        cookie_path: Path | None = None,
        opener: Any | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.use_stored_session = use_stored_session
        self.cookie_path = cookie_path or (default_config_dir() / "cookies.txt")
        self.cookie_jar = http.cookiejar.MozillaCookieJar(str(self.cookie_path))
        if self.use_stored_session and self.cookie_path.exists():
            try:
                self.cookie_jar.load(ignore_discard=True, ignore_expires=False)
            except (OSError, http.cookiejar.LoadError) as exc:
                raise TimefulError(f"Could not load the saved Timeful session: {exc}") from exc
        self._opener = opener or urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookie_jar))

    def _save_session(self) -> None:
        if not self.use_stored_session or not list(self.cookie_jar):
            return
        try:
            self.cookie_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if os.name == "nt":
                self.cookie_jar.save(ignore_discard=True, ignore_expires=False)
            else:
                os.chmod(self.cookie_path.parent, 0o700)
                previous_umask = os.umask(0o077)
                try:
                    self.cookie_jar.save(ignore_discard=True, ignore_expires=False)
                finally:
                    os.umask(previous_umask)
                os.chmod(self.cookie_path, 0o600)
        except OSError as exc:
            raise TimefulError(f"Could not save the Timeful session: {exc}") from exc

    def clear_session(self) -> None:
        self.cookie_jar.clear()
        try:
            self.cookie_path.unlink(missing_ok=True)
        except OSError as exc:
            raise TimefulError(f"Could not remove the saved Timeful session: {exc}") from exc

    def _request(
        self,
        method: str,
        route: str,
        *,
        body: dict[str, Any] | None = None,
    ) -> Any:
        data = None
        headers = {
            "Accept": "application/json",
            "User-Agent": f"timeful-cli/{__version__} (+https://github.com/jaykbpark/timeful-cli)",
        }
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(
            f"{self.base_url}/api{route}",
            data=data,
            headers=headers,
            method=method,
        )

        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            try:
                details = exc.read().decode("utf-8", errors="replace").strip()
            finally:
                exc.close()
            raise TimefulHTTPError(exc.code, exc.reason, details) from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            reason = getattr(exc, "reason", exc)
            raise TimefulError(f"Could not reach Timeful: {reason}") from exc

        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TimefulError("Timeful returned a response that was not valid JSON.") from exc

    def check_email(self, email: str) -> bool:
        response = self._request("POST", "/auth/otp/check-email", body={"email": email})
        if not isinstance(response, dict) or "isNewUser" not in response:
            raise TimefulError("Timeful returned an unexpected email-check response.")
        return bool(response.get("isNewUser"))

    def send_otp(self, email: str) -> None:
        self._request("POST", "/auth/otp/send", body={"email": email})

    def verify_otp(
        self,
        email: str,
        code: str,
        *,
        timezone_offset: int,
        first_name: str = "",
        last_name: str = "",
    ) -> dict[str, Any]:
        response = self._request(
            "POST",
            "/auth/otp/verify",
            body={
                "email": email,
                "code": code,
                "timezoneOffset": timezone_offset,
                "firstName": first_name,
                "lastName": last_name,
            },
        )
        if not isinstance(response, dict):
            raise TimefulError("Timeful returned an unexpected login response.")
        self._save_session()
        return response

    def auth_status(self) -> bool:
        if self.use_stored_session and not list(self.cookie_jar):
            return False
        try:
            self._request("GET", "/auth/status")
        except TimefulHTTPError as exc:
            if exc.status == 401:
                if self.use_stored_session:
                    self.clear_session()
                return False
            raise
        return True

    def sign_out(self) -> None:
        try:
            self._request("POST", "/auth/sign-out", body={})
        except TimefulHTTPError as exc:
            if exc.status != 401:
                raise
        finally:
            self.clear_session()

    def create_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._request("POST", "/events", body=payload)
        if not isinstance(response, dict):
            raise TimefulError("Timeful returned an unexpected event response.")

        public_id = response.get("shortId") or response.get("eventId")
        if public_id:
            prefix = "/g/" if payload.get("type") == "group" else "/s/" if payload.get("isSignUpForm") else "/e/"
            response["url"] = f"{self.base_url}{prefix}{public_id}"
        return response

    def get_event(self, event_id: str) -> Any:
        event_id = urllib.parse.quote(event_id, safe="")
        return self._request("GET", f"/events/{event_id}")

    def get_responses(
        self,
        event_id: str,
        *,
        time_min: str,
        time_max: str,
        guest_name: str | None = None,
    ) -> Any:
        event_id = urllib.parse.quote(event_id, safe="")
        query = urllib.parse.urlencode(
            {
                "timeMin": time_min,
                "timeMax": time_max,
                **({"guestName": guest_name} if guest_name else {}),
            }
        )
        return self._request("GET", f"/events/{event_id}/responses?{query}")

    def set_response(
        self,
        event_id: str,
        *,
        availability: list[str],
        if_needed: list[str],
        as_guest: bool,
        name: str = "",
        email: str | None = None,
    ) -> Any:
        event_id = urllib.parse.quote(event_id, safe="")
        payload: dict[str, Any] = {
            "guest": as_guest,
            "availability": availability,
            "ifNeeded": if_needed,
        }
        if as_guest:
            payload["name"] = name
            if email:
                payload["email"] = email
        return self._request("POST", f"/events/{event_id}/response", body=payload)

    def set_guest_response(
        self,
        event_id: str,
        *,
        name: str,
        availability: list[str],
        if_needed: list[str],
        email: str | None = None,
    ) -> Any:
        return self.set_response(
            event_id,
            name=name,
            email=email,
            availability=availability,
            if_needed=if_needed,
            as_guest=True,
        )
