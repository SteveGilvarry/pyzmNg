"""Tests for ZMAPI with api_backend="v3" (zm-api)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from pyzm.models.config import ZMClientConfig
from pyzm.zm.api import ZMAPI

API = "https://zm.example.com:8080/api/v3"


def _config(**overrides) -> ZMClientConfig:
    defaults = dict(api_url=API, api_backend="v3", user="admin", password="pw", timeout=9)
    defaults.update(overrides)
    return ZMClientConfig(**defaults)


def _json_resp(data, status=200):
    r = MagicMock()
    r.status_code = status
    r.headers = {"content-type": "application/json"}
    r.text = "x"
    r.json.return_value = data
    if status >= 400:
        r.raise_for_status.side_effect = requests.HTTPError(response=r)
    return r


@pytest.fixture
def api():
    with patch("pyzm.zm.api.V3AuthManager") as auth_cls, \
         patch("pyzm.zm.api.requests.Session") as session_cls:
        auth = auth_cls.return_value
        auth.apply_auth.side_effect = lambda url, params: (url, params or {})
        session_cls.return_value = MagicMock()
        yield ZMAPI(_config())


class TestV3Config:
    def test_v3_config_derives_no_portal_url(self):
        assert _config().portal_url is None

    def test_v2_is_default(self):
        cfg = ZMClientConfig(api_url="https://zm/zm/api")
        assert cfg.api_backend == "v2"
        assert cfg.portal_url == "https://zm/zm"

    def test_unknown_backend_rejected(self):
        with pytest.raises(ValueError):
            _config(api_backend="v4")


class TestV3Dispatch:
    def test_uses_v3_auth_manager(self):
        with patch("pyzm.zm.api.V3AuthManager") as v3_cls, \
             patch("pyzm.zm.api.AuthManager") as v2_cls, \
             patch("pyzm.zm.api.requests.Session"):
            api = ZMAPI(_config())
        v3_cls.assert_called_once()
        assert v3_cls.call_args.kwargs["timeout"] == 9
        v2_cls.assert_not_called()
        assert api.is_v3 is True

    def test_post_sends_json_body(self, api):
        api.session.post.return_value = _json_resp({"id": 3})
        assert api.post("tags", data={"name": "person"}) == {"id": 3}
        api.session.post.assert_called_once_with(
            f"{API}/tags", params={}, timeout=9, json={"name": "person"},
        )

    def test_patch_sends_json_body(self, api):
        api.session.patch.return_value = _json_resp({"id": 1})
        api.patch("events/1", data={"notes": "detected"})
        api.session.patch.assert_called_once_with(
            f"{API}/events/1", params={}, timeout=9, json={"notes": "detected"},
        )

    def test_404_on_resource_returns_none(self, api):
        api.session.get.return_value = _json_resp({"kind": "NotFound"}, status=404)
        assert api.get("events/99") is None

    def test_404_on_frame_image_is_bad_image(self, api):
        api.session.get.return_value = _json_resp({"kind": "NotFound"}, status=404)
        with pytest.raises(ValueError, match="BAD_IMAGE"):
            api.request(api.frame_image_url(5, 9))


class TestFrameImageUrl:
    def test_v3_frame_url(self, api):
        assert api.frame_image_url(5, "snapshot") == f"{API}/events/5/frames/snapshot/image"

    def test_v2_frame_url(self):
        with patch("pyzm.zm.api.AuthManager"), patch("pyzm.zm.api.requests.Session"):
            api = ZMAPI(ZMClientConfig(api_url="https://zm/zm/api"))
        assert api.is_v3 is False
        assert api.frame_image_url(5, 1) == "https://zm/zm/index.php?view=image&eid=5&fid=1"
