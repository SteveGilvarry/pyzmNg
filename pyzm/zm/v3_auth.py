"""Authentication for zm-api (the ``/api/v3`` REST server).

zm-api issues a JWT access token and a refresh token from ``POST auth/login``
(JSON ``username``/``password``).  API calls carry the access token in an
``Authorization: Bearer`` header; media endpoints also accept ``?token=``,
which is what :meth:`get_auth_string` returns for URLs handed to other
processes (the remote ML gateway).

Exposes the same surface as :class:`pyzm.zm.auth.AuthManager` so
:class:`pyzm.zm.api.ZMAPI` can use either.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import requests

logger = logging.getLogger("pyzm.zm")

# Refresh this many seconds before the access token expires, capped at half
# its lifetime so a short-lived token isn't refreshed on every request.
_REFRESH_GRACE_SECONDS = 5 * 60


class V3AuthManager:
    """Manages zm-api JWT authentication.

    Parameters
    ----------
    session:
        The ``requests.Session`` shared with :class:`ZMAPI`.  The Bearer
        header is set on it, so every request through the session is
        authenticated.
    api_url:
        Base zm-api URL including the version prefix, e.g.
        ``https://zm.example.com:8080/api/v3``.
    user, password:
        zm-api credentials.  ``None`` skips login (only the public version
        endpoint will work).
    timeout:
        Seconds for each auth request.
    """

    def __init__(
        self,
        session: requests.Session,
        api_url: str,
        user: str | None,
        password: str | None,
        timeout: int = 30,
    ) -> None:
        self._session = session
        self._api_url = api_url.rstrip("/")
        self._user = user
        self._password = password
        self._timeout = timeout

        self.api_version: str | None = None
        self.zm_version: str | None = None
        self.auth_enabled: bool = bool(user and password)

        self._access_token: str = ""
        self._refresh_token: str = ""
        self._refresh_at: datetime | None = None

    # ------------------------------------------------------------------
    # Public API (mirrors AuthManager)
    # ------------------------------------------------------------------

    def login(self) -> None:
        """Log in with username/password, then fetch version info.

        Raises ``requests.HTTPError`` on failure.
        """
        if self.auth_enabled:
            logger.debug("Attempting zm-api login")
            resp = self._session.post(
                f"{self._api_url}/auth/login",
                json={"username": self._user, "password": self._password},
                timeout=self._timeout,
            )
            resp.raise_for_status()
            self._store_tokens(resp.json())
        else:
            logger.debug("No zm-api credentials; fetching version only")
        self._fetch_version()

    def apply_auth(
        self, url: str, params: dict[str, str] | None = None,
    ) -> tuple[str, dict[str, str]]:
        """Return *url* and *params* unchanged; the session header carries auth."""
        return url, dict(params) if params else {}

    def refresh_if_needed(self) -> None:
        """Refresh the access token when it is close to expiry."""
        if not self.auth_enabled or self._refresh_at is None:
            return
        if datetime.now() < self._refresh_at:
            return
        logger.debug("zm-api access token expires soon; refreshing")
        self._relogin()

    def handle_401(self) -> None:
        """Called when a request gets HTTP 401."""
        logger.debug("Handling 401 from zm-api -- refreshing token")
        self._relogin()

    def get_auth_string(self) -> str:
        """Query-string fragment for media URLs (``token=<access token>``)."""
        if not self.auth_enabled or not self._access_token:
            return ""
        return f"token={self._access_token}"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _store_tokens(self, rj: dict) -> None:
        self._access_token = rj.get("access_token", "")
        self._refresh_token = rj.get("refresh_token", "") or self._refresh_token
        self._session.headers["Authorization"] = f"Bearer {self._access_token}"

        expire_in = int(rj.get("expire_in") or 0)
        if expire_in > 0:
            grace = min(_REFRESH_GRACE_SECONDS, expire_in // 2)
            self._refresh_at = datetime.now() + timedelta(seconds=expire_in - grace)
            logger.debug("zm-api access token valid for %d s", expire_in)
        else:
            self._refresh_at = None

    def _fetch_version(self) -> None:
        resp = self._session.get(
            f"{self._api_url}/host/getVersion", timeout=self._timeout,
        )
        resp.raise_for_status()
        rj = resp.json()
        self.zm_version = rj.get("version")
        self.api_version = rj.get("api_version")

    def _relogin(self) -> None:
        """Use the refresh token; fall back to a full login if it is rejected."""
        if self._refresh_token:
            resp = self._session.post(
                f"{self._api_url}/auth/refresh",
                json={"token": self._refresh_token},
                timeout=self._timeout,
            )
            if resp.ok:
                self._store_tokens(resp.json())
                return
            logger.debug(
                "zm-api refresh returned %d; logging in again", resp.status_code,
            )
        self.login()
