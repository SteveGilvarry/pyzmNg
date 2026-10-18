"""Tests for pyzm.zm.v3_auth -- zm-api JWT authentication."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
import requests

from pyzm.zm.v3_auth import V3AuthManager

API = "https://zm.example.com:8080/api/v3"


def _resp(json_data=None, status=200):
    r = MagicMock()
    r.status_code = status
    r.ok = status < 400
    r.json.return_value = json_data or {}
    if status >= 400:
        err = requests.HTTPError(response=r)
        r.raise_for_status.side_effect = err
    return r


def _token(access="ACC1", refresh="REF1", expire_in=3600):
    return {"token_type": "Bearer", "access_token": access,
            "refresh_token": refresh, "expire_in": expire_in}


VERSION = {"version": "1.38.0", "api_version": "3.0.0", "db_version": "1.38.0"}


def _session(post_responses):
    session = MagicMock()
    session.headers = {}
    session.post.side_effect = list(post_responses)
    session.get.return_value = _resp(VERSION)
    return session


class TestV3Login:
    def test_login_posts_json_credentials_with_timeout(self):
        session = _session([_resp(_token())])
        V3AuthManager(session, API, "admin", "pw", timeout=7).login()

        session.post.assert_called_once_with(
            f"{API}/auth/login", json={"username": "admin", "password": "pw"}, timeout=7,
        )

    def test_login_sets_bearer_header_and_versions(self):
        session = _session([_resp(_token(access="ACC1"))])
        auth = V3AuthManager(session, API, "admin", "pw")
        auth.login()

        assert session.headers["Authorization"] == "Bearer ACC1"
        assert auth.zm_version == "1.38.0"
        assert auth.api_version == "3.0.0"
        session.get.assert_called_once_with(f"{API}/host/getVersion", timeout=30)

    def test_login_failure_raises(self):
        session = _session([_resp(status=400)])
        with pytest.raises(requests.HTTPError):
            V3AuthManager(session, API, "admin", "bad").login()

    def test_no_credentials_skips_login(self):
        session = _session([])
        auth = V3AuthManager(session, API, None, None)
        auth.login()

        session.post.assert_not_called()
        assert auth.auth_enabled is False
        assert auth.zm_version == "1.38.0"
        assert auth.get_auth_string() == ""


class TestV3Auth:
    def test_apply_auth_leaves_url_and_params_alone(self):
        session = _session([_resp(_token())])
        auth = V3AuthManager(session, API, "admin", "pw")
        auth.login()

        url, params = auth.apply_auth(f"{API}/monitors", {"page": "1"})
        assert url == f"{API}/monitors"
        assert params == {"page": "1"}

    def test_auth_string_is_query_token(self):
        session = _session([_resp(_token(access="ACC9"))])
        auth = V3AuthManager(session, API, "admin", "pw")
        auth.login()
        assert auth.get_auth_string() == "token=ACC9"


class TestV3Refresh:
    def test_no_refresh_while_token_fresh(self):
        session = _session([_resp(_token())])
        auth = V3AuthManager(session, API, "admin", "pw")
        auth.login()
        auth.refresh_if_needed()
        assert session.post.call_count == 1

    def test_refresh_near_expiry_uses_refresh_token(self):
        session = _session([_resp(_token(refresh="REF1")), _resp(_token(access="ACC2"))])
        auth = V3AuthManager(session, API, "admin", "pw")
        auth.login()
        auth._refresh_at = datetime.now() - timedelta(seconds=1)

        auth.refresh_if_needed()

        assert session.post.call_args_list[1].args == (f"{API}/auth/refresh",)
        assert session.post.call_args_list[1].kwargs["json"] == {"token": "REF1"}
        assert session.headers["Authorization"] == "Bearer ACC2"

    def test_short_lived_token_refreshes_at_half_life(self):
        session = _session([_resp(_token(expire_in=120))])
        auth = V3AuthManager(session, API, "admin", "pw")
        before = datetime.now()
        auth.login()
        # 120 s token, 5 min grace capped at 60 s -> refresh ~60 s from now
        assert timedelta(seconds=55) < auth._refresh_at - before < timedelta(seconds=65)

    def test_rejected_refresh_falls_back_to_login(self):
        session = _session([
            _resp(_token()),           # login
            _resp(status=401),         # refresh rejected
            _resp(_token(access="ACC3")),  # login again
        ])
        auth = V3AuthManager(session, API, "admin", "pw")
        auth.login()

        auth.handle_401()

        assert session.post.call_args_list[2].args == (f"{API}/auth/login",)
        assert session.headers["Authorization"] == "Bearer ACC3"
