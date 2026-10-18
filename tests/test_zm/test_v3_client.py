"""Tests for pyzm.zm.v3_client -- ZMClient on zm-api (/api/v3)."""

from __future__ import annotations

import inspect
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
import requests

from pyzm.client import ZMClient
from pyzm.models.config import ZMClientConfig
from pyzm.zm.v3_client import ZMClientV3

API = "https://zm.example.com:8080/api/v3"


def _page(items, page=1, last_page=1):
    return {"items": items, "total": len(items), "per_page": 1000,
            "current_page": page, "last_page": last_page}


def _monitor(mid=1, **kw):
    m = {"id": mid, "name": f"Cam {mid}", "function": "Modect", "enabled": 1,
         "width": 1920, "height": 1080, "type": "Ffmpeg", "controllable": 0,
         "control_id": None, "capturing": "Always"}
    m.update(kw)
    return m


def _event(eid=12, **kw):
    e = {"id": eid, "monitor_id": 1, "storage_id": 2, "name": f"Event {eid}",
         "cause": "Motion", "notes": None, "length": "90.50", "frames": 270,
         "alarm_frames": 45, "max_score": 97, "scheme": "Medium",
         "start_date_time": "2024-03-15T10:30:00Z", "end_date_time": "2024-03-15T10:31:30Z"}
    e.update(kw)
    return e


def _http_error(status):
    r = MagicMock()
    r.status_code = status
    return requests.HTTPError(response=r)


@pytest.fixture
def api():
    with patch("pyzm.client.ZMAPI") as zmapi_cls:
        mock = MagicMock()
        mock.is_v3 = True
        mock.api_url = API
        mock.portal_url = None
        zmapi_cls.return_value = mock
        yield mock


@pytest.fixture
def zm(api):
    return ZMClient(api_url=API, user="admin", password="pw", api_backend="v3")


def _route(api, routes):
    """Answer api.get(endpoint, params=...) from {endpoint: value or callable}."""
    def get(endpoint, params=None):
        val = routes[endpoint]
        return val(params or {}) if callable(val) else val
    api.get.side_effect = get


# ===================================================================
# Construction
# ===================================================================

class TestConstruction:
    def test_api_backend_kwarg_returns_v3_client(self, zm):
        assert type(zm) is ZMClientV3
        assert zm._config.api_backend == "v3"

    def test_config_returns_v3_client(self, api):
        cfg = ZMClientConfig(api_url=API, api_backend="v3")
        assert type(ZMClient(config=cfg)) is ZMClientV3

    def test_default_stays_v2(self, api):
        assert type(ZMClient(api_url="https://zm/zm/api")) is ZMClient


def test_every_server_call_is_overridden():
    """A v2 method left un-overridden would send CakePHP requests to zm-api."""
    exempt = {"_get_event_frames", "_get_db", "_update_notification_last_sent"}
    missing = []
    for name, fn in inspect.getmembers(ZMClient, inspect.isfunction):
        src = inspect.getsource(fn)
        if ("self._api." in src or "self._get_db()" in src) and name not in exempt:
            if name not in ZMClientV3.__dict__:
                missing.append(name)
    assert missing == []


# ===================================================================
# Monitors
# ===================================================================

class TestMonitors:
    def test_pages_through_monitors_and_merges_status(self, zm, api):
        def monitors(params):
            if params["page"] == "1":
                return _page([_monitor(1)], page=1, last_page=2)
            return _page([_monitor(2, enabled=0)], page=2, last_page=2)
        _route(api, {
            "monitors": monitors,
            "monitor-status": _page([{"monitor_id": 1, "status": "Connected",
                                      "capture_fps": "15.00", "analysis_fps": "5.00",
                                      "capture_bandwidth": 1000, "updated_on": "x"}]),
        })

        mons = zm.monitors()

        assert [(m.id, m.name, m.enabled) for m in mons] == [(1, "Cam 1", True), (2, "Cam 2", False)]
        assert mons[0].status.state == "Connected"
        assert mons[0].status.fps == 15.0
        assert mons[1].status.state == ""
        assert mons[0].raw()["capturing"] == "Always"

    def test_monitor_status_forbidden_still_lists_monitors(self, zm, api):
        def get(endpoint, params=None):
            if endpoint == "monitor-status":
                raise _http_error(403)
            return _page([_monitor(1)])
        api.get.side_effect = get
        assert [m.id for m in zm.monitors()] == [1]

    def test_monitor_fallback_fetches_by_id(self, zm, api):
        _route(api, {"monitors": _page([]), "monitor-status": _page([]),
                     "monitors/7": _monitor(7), "monitor-status/7": None})
        assert zm.monitor(7).name == "Cam 7"

    def test_update_maps_v2_names_and_types(self, zm, api):
        zm._update_monitor(3, Function="Record", Enabled="1", Name="123")
        api.patch.assert_called_once_with(
            "monitors/3", data={"function": "Record", "enabled": 1, "name": "123"},
        )

    def test_arm_and_disarm(self, zm, api):
        zm._arm(4)
        zm._disarm(4)
        assert [c.args for c in api.patch.call_args_list] == [
            ("monitors/4/alarm",), ("monitors/4/alarm",)]
        assert [c.kwargs["data"] for c in api.patch.call_args_list] == [
            {"action": "on"}, {"action": "off"}]

    def test_zones_percent_to_pixels(self, zm, api):
        _route(api, {
            "monitors/1/zones": _page([{"name": "drive", "units": "Percent",
                                        "coords": "0,0 50,0 50,50"}]),
            "monitors/1": _monitor(1, width=200, height=100),
        })
        zones = zm._monitor_zones(1)
        assert zones[0].name == "drive"
        assert zones[0].points == [(0, 0), (100, 0), (100, 50)]

    def test_daemon_status_shaped_like_v2(self, zm, api):
        _route(api, {"daemons": {"daemons": [
            {"id": "zmc -m 2", "name": "zmc", "monitor_id": 2, "state": "running",
             "restart_count": 0}]}})
        st = zm._daemon_status(2)
        assert st["status"] is True
        assert "running" in st["statustext"]

    def test_snapshot_url(self, zm):
        assert zm._snapshot_url(5) == f"{API}/monitors/5/snapshot"

    def test_mjpeg_not_available(self, zm):
        with pytest.raises(NotImplementedError):
            zm._streaming_url_mjpeg(1)


class TestPTZ:
    def test_continuous_move_with_stop_after_uses_duration(self, zm, api):
        zm._ptz_command(1, "up_left", stop_after=1.5)
        api.post.assert_called_once_with(
            "ptz/monitors/1/move/up-left", data={"duration_ms": 1500})

    @pytest.mark.parametrize("cmd, kwargs, path", [
        ("stop", {}, "move/stop"),
        ("home", {}, "home"),
        ("preset", {"preset": 3}, "presets/3/goto"),
        ("zoom_out", {}, "zoom/out"),
    ])
    def test_commands(self, zm, api, cmd, kwargs, path):
        zm._ptz_command(1, cmd, **kwargs)
        api.post.assert_called_once_with(f"ptz/monitors/1/{path}", data=None)

    def test_relative_mode_rejected(self, zm, api):
        with pytest.raises(ValueError, match="continuous"):
            zm._ptz_command(1, "up", mode="rel")
        api.post.assert_not_called()

    def test_unknown_command_rejected(self, zm, api):
        with pytest.raises(ValueError, match="Unknown PTZ command"):
            zm._ptz_command(1, "spin")

    def test_capabilities_from_int_flags(self, zm, api):
        _route(api, {"controls/2": {"id": 2, "can_move": 1, "can_move_con": 1,
                                    "can_zoom": 0, "num_presets": 4, "has_presets": 1}})
        caps = zm._ptz_capabilities(2)
        assert (caps.can_move, caps.can_move_con, caps.can_zoom) == (True, True, False)
        assert (caps.has_presets, caps.num_presets) == (True, 4)


# ===================================================================
# Events
# ===================================================================

class TestEvents:
    def test_filters_become_query_params(self, zm, api):
        api.get.return_value = _page([_event(12)])
        with patch("pyzm.zm.v3_client.utc_iso", side_effect=lambda s: f"ISO({s})"):
            evs = zm.events(monitor_id=1, since="1 hour ago", until="now",
                            min_alarm_frames=5, object_only=True, limit=20)

        api.get.assert_called_once_with("events", params={
            "page": "1", "page_size": "20", "monitor_id": "1",
            "start_time": "ISO(1 hour ago)", "end_time": "ISO(now)",
            "alarm_frames_min": "5", "notes": "detected"})
        assert [e.id for e in evs] == [12]

    def test_event_id_filter_fetches_one(self, zm, api):
        _route(api, {"events/12": _event(12)})
        assert [e.id for e in zm.events(event_id=12)] == [12]

    def test_event_fields(self, zm, api):
        _route(api, {"events/12": _event(12)})
        ev = zm.event(12)
        expected_start = datetime(2024, 3, 15, 10, 30, tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
        assert ev.start_time == expected_start
        assert (ev.length, ev.frames, ev.alarm_frames, ev.max_score) == (90.5, 270, 45, 97)
        assert ev.notes == ""
        assert ev.max_score_frame_id is None

    def test_missing_event_raises(self, zm, api):
        _route(api, {"events/9": None})
        with pytest.raises(ValueError, match="Event 9 not found"):
            zm.event(9)

    def test_update_notes_and_delete(self, zm, api):
        zm._update_event_notes(12, "detected: person")
        api.get.return_value = _page([_event(12), _event(13)])
        assert zm.delete_events(monitor_id=1) == 2
        api.patch.assert_called_once_with("events/12", data={"notes": "detected: person"})
        assert [c.args for c in api.delete.call_args_list] == [("events/12",), ("events/13",)]

    def test_frames(self, zm, api):
        _route(api, {"frames": lambda p: _page([
            {"id": 1, "event_id": int(p["event_id"]), "frame_id": 3, "type": "Alarm",
             "time_stamp": "x", "delta": "0.40", "score": 55}])})
        frames = zm._event_frames(12)
        assert [(f.frame_id, f.event_id, f.type, f.score, f.delta) for f in frames] == [
            (3, 12, "Alarm", 55, 0.4)]


class TestTagging:
    def test_reuses_existing_tag_and_creates_new(self, zm, api):
        _route(api, {"tags": _page([{"id": 7, "name": "Person"}])})
        api.post.side_effect = lambda ep, data=None: {"id": 8} if ep == "tags" else {}

        zm._tag_event(12, ["person", "car", "person"])

        assert [c.args + (c.kwargs.get("data"),) for c in api.post.call_args_list] == [
            ("events-tags", {"event_id": 12, "tag_id": 7}),
            ("tags", {"name": "car"}),
            ("events-tags", {"event_id": 12, "tag_id": 8}),
        ]

    def test_duplicate_link_is_not_an_error(self, zm, api):
        _route(api, {"tags": _page([{"id": 7, "name": "person"}])})
        api.post.side_effect = _http_error(409)
        zm._tag_event(12, ["person"])  # does not raise

    def test_no_db_access(self, zm, api):
        _route(api, {"tags": _page([])})
        api.post.return_value = {"id": 1}
        with patch.object(ZMClient, "_get_db", side_effect=AssertionError("DB used")):
            zm._tag_event(12, ["dog"])


class TestEventPath:
    def test_medium_scheme_from_storage(self, zm, api):
        _route(api, {"events/12": _event(12, start_date_time="2024-03-15T10:30:00Z"),
                     "storage/2": {"id": 2, "path": "/var/cache/zm/events", "scheme": "Medium"}})
        day = datetime(2024, 3, 15, 10, 30, tzinfo=timezone.utc).astimezone().strftime("%Y-%m-%d")
        assert zm._event_path(12) == f"/var/cache/zm/events/1/{day}/12"

    def test_bad_storage_falls_back_to_id_1(self, zm, api):
        _route(api, {"events/12": _event(12, scheme="Shallow"), "storage/2": None,
                     "storage/1": {"id": 1, "path": "/zm", "scheme": None}})
        assert zm._event_path(12) == "/zm/1/12"


# ===================================================================
# System, configs, states, notifications
# ===================================================================

class TestSystem:
    def test_configs_use_v2_keys(self, zm, api):
        _route(api, {"configs": _page([{"id": 1, "name": "ZM_LANG", "value": "en_gb"}]),
                     "configs/ZM_LANG": {"id": 1, "name": "ZM_LANG", "value": "en_gb"}})
        assert zm.configs() == [{"Id": 1, "Name": "ZM_LANG", "Value": "en_gb"}]
        assert zm.config("ZM_LANG")["Value"] == "en_gb"

    def test_set_config(self, zm, api):
        zm.set_config("ZM_LANG", "de_de")
        api.put.assert_called_once_with("configs/ZM_LANG", data={"value": "de_de"})

    @pytest.mark.parametrize("state, call", [
        ("restart", ("server/control/restart",)),
        ("Away", ("system/state",)),
    ])
    def test_set_state(self, zm, api, state, call):
        zm.set_state(state)
        assert api.post.call_args.args == call

    def test_status_load_disk_timezone(self, zm, api):
        _route(api, {"system/status": {"running": True, "daemons": [], "stats": {
                         "cpu_load": 0.5, "total_disk": 100, "used_disk": 40,
                         "free_disk": 60, "disk_usage_percent": 40.0}},
                     "system/locale": {"timezone": "Australia/Melbourne"}})
        assert zm.is_running() is True
        assert zm.system_load() == {"1min": 0.5}
        assert zm.disk_usage()["disk_usage_percent"] == 40.0
        assert zm.timezone() == "Australia/Melbourne"

    def test_passive_mode_503_reads_as_unknown(self, zm, api):
        api.get.side_effect = _http_error(503)
        assert zm.is_running() is False
        assert zm.system_load() == {}
        assert zm.disk_usage() == {}
        assert zm._daemon_status(1) == {}

    def test_other_daemon_errors_raise(self, zm, api):
        api.get.side_effect = _http_error(500)
        with pytest.raises(requests.HTTPError):
            zm.is_running()

    def test_notifications_not_available(self, zm):
        with pytest.raises(NotImplementedError, match="notifications"):
            zm.notifications()


def test_utc_iso_converts_local_to_utc():
    from pyzm.zm.v3_parse import utc_iso
    local = datetime(2024, 3, 15, 10, 30).astimezone()
    expected = local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert utc_iso("2024-03-15 10:30:00") == expected
