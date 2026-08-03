"""Small dependency-free client for Timeful's public event endpoints."""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from . import __version__


DEFAULT_BASE_URL = "https://timeful.app"


class TimefulError(RuntimeError):
    """A friendly error returned by Timeful or the network."""


class TimefulClient:
    def __init__(self, base_url: str = DEFAULT_BASE_URL, timeout: float = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

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
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace").strip()
            suffix = f"\n{details}" if details else ""
            raise TimefulError(f"Timeful returned HTTP {exc.code} {exc.reason}.{suffix}") from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            reason = getattr(exc, "reason", exc)
            raise TimefulError(f"Could not reach Timeful: {reason}") from exc

        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TimefulError("Timeful returned a response that was not valid JSON.") from exc

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

    def set_guest_response(
        self,
        event_id: str,
        *,
        name: str,
        availability: list[str],
        if_needed: list[str],
        email: str | None = None,
    ) -> Any:
        event_id = urllib.parse.quote(event_id, safe="")
        payload: dict[str, Any] = {
            "guest": True,
            "name": name,
            "availability": availability,
            "ifNeeded": if_needed,
        }
        if email:
            payload["email"] = email
        return self._request("POST", f"/events/{event_id}/response", body=payload)
