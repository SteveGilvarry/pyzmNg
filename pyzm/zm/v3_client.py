"""ZMClient for zm-api, the Rust ``/api/v3`` server.

Construct it through :class:`pyzm.ZMClient` with ``api_backend="v3"``::

    zm = ZMClient(api_url="https://zm.example.com:8080/api/v3",
                  user="admin", password="secret", api_backend="v3")

Every ZMClient method that talks to the server is overridden here, so a v3
client never sends a CakePHP request.  Tagging and event paths go through
the API instead of the ZoneMinder database.

Not available on zm-api: push notification registrations (no endpoint),
MJPEG/ZMS streaming URLs (zm-api streams HLS and WebRTC), and relative or
absolute PTZ moves through :meth:`Monitor.ptz` (continuous moves, presets,
home and stop work).
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

import requests

from pyzm.client import (
    _PTZ_MOVE_MAP,
    _PTZ_ZOOM_MAP,
    ZMClient,
    _event_dir,
    _parse_zone_coords,
    _ptz_command_name,
)
from pyzm.models.zm import Event, Frame, Monitor, Notification, PTZCapabilities, Zone
from pyzm.zm.v3_parse import (
    event_from_v3,
    frame_from_v3,
    local_naive,
    monitor_from_v3,
    monitor_update_body,
    ptz_from_v3,
    to_camel,
    utc_iso,
)

logger = logging.getLogger("pyzm")

# zm-api's MAX_PAGE_SIZE; list calls page through results at this size.
_PAGE_SIZE = 1000

_NO_NOTIFICATIONS = "zm-api (v3) has no notifications endpoint"


class ZMClientV3(ZMClient):
    """ZMClient backed by zm-api.  See the module docstring."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_all(self, endpoint: str, params: dict[str, str] | None = None) -> list[dict]:
        """GET every page of a paginated zm-api list."""
        items: list[dict] = []
        page = 1
        while True:
            data = self._api.get(
                endpoint,
                params={**(params or {}), "page": str(page), "page_size": str(_PAGE_SIZE)},
            )
            if not data:
                break
            items.extend(data.get("items", []))
            if page >= int(data.get("last_page") or 1):
                break
            page += 1
        return items

    def _get_daemon_manager(self, endpoint: str) -> dict:
        """GET a daemon-controller endpoint; ``{}`` when zm-api runs passive.

        In passive mode ZoneMinder supervises its own daemons and zm-api
        answers these endpoints with 503.
        """
        try:
            return self._api.get(endpoint) or {}
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 503:
                logger.debug("zm-api daemon manager unavailable (passive mode): %s", endpoint)
                return {}
            raise

    # ------------------------------------------------------------------
    # Monitors
    # ------------------------------------------------------------------

    def monitors(self, *, force_reload: bool = False) -> list[Monitor]:
        if self._monitors is not None and not force_reload:
            return self._monitors
        statuses = self._monitor_statuses()
        self._monitors = [
            monitor_from_v3(m, statuses.get(m.get("id")), client=self)
            for m in self._get_all("monitors")
        ]
        return self._monitors

    def _monitor_statuses(self) -> dict[int, dict]:
        """Runtime status rows keyed by monitor id; empty if unavailable."""
        try:
            return {s["monitor_id"]: s for s in self._get_all("monitor-status")}
        except requests.HTTPError as exc:
            logger.debug("monitor-status unavailable: %s", exc.response.status_code
                         if exc.response is not None else exc)
            return {}

    def _fetch_monitor(self, monitor_id: int) -> Monitor | None:
        data = self._api.get(f"monitors/{monitor_id}")
        if not data:
            return None
        status = self._api.get(f"monitor-status/{monitor_id}")
        return monitor_from_v3(data, status, client=self)

    def _monitor_zones(self, monitor_id: int) -> list[Zone]:
        raw_zones = self._get_all(f"monitors/{monitor_id}/zones")
        mon_w = mon_h = 0
        if any(z.get("units") == "Percent" for z in raw_zones):
            mon = self._api.get(f"monitors/{monitor_id}") or {}
            mon_w, mon_h = int(mon.get("width") or 0), int(mon.get("height") or 0)
        zones: list[Zone] = []
        for z in raw_zones:
            points = _parse_zone_coords(z.get("coords", ""))
            if z.get("units") == "Percent" and mon_w and mon_h:
                points = [(int(round(x * mon_w / 100.0)), int(round(y * mon_h / 100.0)))
                          for x, y in points]
            zones.append(Zone(name=z.get("name", ""), points=points, _raw=z))
        return zones

    def _arm(self, monitor_id: int) -> dict:
        return self._api.patch(f"monitors/{monitor_id}/alarm", data={"action": "on"})

    def _disarm(self, monitor_id: int) -> dict:
        return self._api.patch(f"monitors/{monitor_id}/alarm", data={"action": "off"})

    def _alarm_status(self, monitor_id: int) -> dict:
        """The monitor's ``monitor-status`` row (``status`` is Idle/Alarm/...)."""
        return self._api.get(f"monitor-status/{monitor_id}") or {}

    def _update_monitor(self, monitor_id: int, **kwargs) -> None:
        """Update monitor fields; accepts v2 names (``Function="Modect"``)."""
        self._api.patch(f"monitors/{monitor_id}", data=monitor_update_body(kwargs))
        self._monitors = None

    def _zms_url(self, monitor_id: int, mode: str, **kwargs) -> str:
        raise NotImplementedError(
            "zm-api has no ZMS/MJPEG streams; use its HLS or WebRTC live endpoints"
        )

    def _streaming_url_mjpeg(self, monitor_id: int, **kwargs) -> str:
        return self._zms_url(monitor_id, "jpeg", **kwargs)

    def _snapshot_url(self, monitor_id: int, **kwargs) -> str:
        url = f"{self._api.api_url}/monitors/{monitor_id}/snapshot"
        return f"{url}?{urlencode(kwargs)}" if kwargs else url

    def _daemon_status(self, monitor_id: int) -> dict:
        """Status of the monitor's zmc, shaped like v2 (``status``, ``statustext``)."""
        data = self._get_daemon_manager("daemons")
        for d in data.get("daemons", []):
            if d.get("monitor_id") == monitor_id and str(d.get("id", "")).startswith("zmc"):
                return {
                    "status": d.get("state") == "running",
                    "statustext": f"{d.get('name', d.get('id'))}: {d.get('state')}",
                    "daemon": d,
                }
        return {}

    def _ptz_capabilities(self, control_id: int) -> PTZCapabilities:
        data = self._api.get(f"controls/{control_id}")
        if not data:
            raise ValueError(f"Control profile {control_id} not found")
        return ptz_from_v3(data)

    def _ptz_command(
        self, monitor_id: int, command: str, *, mode: str = "con",
        preset: int = 1, stop_after: float | None = None,
    ) -> None:
        """Send a PTZ command through zm-api's ``ptz/monitors/{id}`` routes.

        *stop_after* becomes the request's ``duration_ms``, so zm-api stops
        the move itself.
        """
        cmd = command.lower().strip()
        body: dict[str, Any] | None = None
        if cmd == "stop":
            action = "move/stop"
        elif cmd == "home":
            action = "home"
        elif cmd == "preset":
            action = f"presets/{preset}/goto"
        elif cmd in _PTZ_MOVE_MAP or cmd in _PTZ_ZOOM_MAP:
            if mode != "con":
                raise ValueError(
                    f"zm-api supports continuous PTZ moves only, not mode {mode!r}"
                )
            if cmd in _PTZ_MOVE_MAP:
                action = "move/" + cmd.replace("_", "-")
            else:
                action = "zoom/in" if cmd == "zoom_in" else "zoom/out"
            if stop_after is not None and stop_after > 0:
                body = {"duration_ms": int(stop_after * 1000)}
        else:
            _ptz_command_name(command, mode=mode, preset=preset)  # raises ValueError
            return
        self._api.post(f"ptz/monitors/{monitor_id}/{action}", data=body)

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def events(
        self,
        *,
        event_id: int | None = None,
        monitor_id: int | None = None,
        since: str | None = None,
        until: str | None = None,
        min_alarm_frames: int | None = None,
        object_only: bool = False,
        limit: int = 100,
    ) -> list[Event]:
        """Query events.

        On zm-api *until* matches the event's end time, so events still
        recording are not returned when it is set.
        """
        if event_id is not None:
            data = self._api.get(f"events/{event_id}")
            return [event_from_v3(data, client=self)] if data else []

        params: dict[str, str] = {"page": "1", "page_size": str(limit)}
        if monitor_id is not None:
            params["monitor_id"] = str(monitor_id)
        if since and (start := utc_iso(since)):
            params["start_time"] = start
        if until and (end := utc_iso(until)):
            params["end_time"] = end
        if min_alarm_frames is not None:
            params["alarm_frames_min"] = str(min_alarm_frames)
        if object_only:
            params["notes"] = "detected"

        data = self._api.get("events", params=params)
        return [event_from_v3(e, client=self) for e in (data or {}).get("items", [])]

    def event(self, event_id: int) -> Event:
        data = self._api.get(f"events/{event_id}")
        if data:
            return event_from_v3(data, client=self)
        raise ValueError(f"Event {event_id} not found")

    def _delete_event(self, event_id: int) -> None:
        self._api.delete(f"events/{event_id}")

    def _update_event_notes(self, event_id: int, notes: str) -> None:
        self._api.patch(f"events/{event_id}", data={"notes": notes})

    def _tag_event(self, event_id: int, labels: list[str]) -> None:
        """Tag an event with each label through the tags API (no DB access)."""
        unique = list(dict.fromkeys(labels))
        if not unique:
            return
        logger.debug("Tagging event %s with %s", event_id, unique)
        existing = {t["name"].lower(): t["id"] for t in self._get_all("tags")}
        for label in unique:
            try:
                tag_id = existing.get(label.lower())
                if tag_id is None:
                    tag_id = self._api.post("tags", data={"name": label})["id"]
                    existing[label.lower()] = tag_id
                self._api.post("events-tags", data={"event_id": event_id, "tag_id": tag_id})
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else 0
                if status == 409:
                    logger.debug("Tag '%s' already linked to event %s", label, event_id)
                else:
                    logger.warning("Could not tag event %s with '%s': HTTP %s",
                                   event_id, label, status)

    def _tag_one(self, label: str, event_id: int) -> None:
        self._tag_event(event_id, [label])

    def _event_path(self, event_id: int) -> str | None:
        """Event directory from the event and storage rows (no DB access)."""
        ev = self._api.get(f"events/{event_id}")
        start_dt = local_naive((ev or {}).get("start_date_time"))
        if not ev or start_dt is None:
            logger.warning("Cannot resolve event path: missing fields for event %s", event_id)
            return None

        storage = self._api.get(f"storage/{ev['storage_id']}") if ev.get("storage_id") else None
        if not storage or not storage.get("path"):
            logger.error("Event %s has StorageId=%s which does not map to a valid "
                         "Storage row. Falling back to Storage Id=1.",
                         event_id, ev.get("storage_id"))
            storage = self._api.get("storage/1")
        if not storage or not storage.get("path"):
            logger.warning("Cannot resolve event path: no storage path for event %s", event_id)
            return None

        scheme = storage.get("scheme") or ev.get("scheme")
        return _event_dir(storage["path"], scheme, ev["monitor_id"], event_id, start_dt)

    def _event_frames(self, event_id: int) -> list[Frame]:
        return [frame_from_v3(f, event_id)
                for f in self._get_all("frames", {"event_id": str(event_id)})]

    # ------------------------------------------------------------------
    # Notifications (no zm-api endpoint)
    # ------------------------------------------------------------------

    def notifications(self) -> list[Notification]:
        raise NotImplementedError(_NO_NOTIFICATIONS)

    def notification(self, notification_id: int) -> Notification:
        raise NotImplementedError(_NO_NOTIFICATIONS)

    def _create_notification(self, **kwargs) -> dict:
        raise NotImplementedError(_NO_NOTIFICATIONS)

    def _update_notification(self, notification_id: int, **kwargs) -> dict:
        raise NotImplementedError(_NO_NOTIFICATIONS)

    def _delete_notification(self, notification_id: int) -> None:
        raise NotImplementedError(_NO_NOTIFICATIONS)

    # ------------------------------------------------------------------
    # System
    # ------------------------------------------------------------------

    def is_running(self) -> bool:
        """True when zm-api's daemon controller reports itself running.

        False when zm-api runs passive, where it cannot see the daemons.
        """
        return bool(self._get_daemon_manager("system/status").get("running"))

    def _system_stats(self) -> dict:
        return self._get_daemon_manager("system/status").get("stats") or {}

    def system_load(self) -> dict[str, float]:
        """Load average; zm-api reports only the 1-minute value."""
        stats = self._system_stats()
        return {"1min": float(stats["cpu_load"])} if "cpu_load" in stats else {}

    def disk_usage(self) -> dict:
        stats = self._system_stats()
        keys = ("total_disk", "used_disk", "free_disk", "disk_usage_percent")
        return {k: stats[k] for k in keys if k in stats}

    def timezone(self) -> str:
        data = self._api.get("system/locale")
        return (data or {}).get("timezone") or ""

    def configs(self) -> list[dict]:
        return [to_camel(c) for c in self._get_all("configs")]

    def config(self, name: str) -> dict:
        data = self._api.get(f"configs/{name}")
        if data:
            return to_camel(data)
        raise ValueError(f"Config '{name}' not found")

    def set_config(self, name: str, value: str) -> None:
        self._api.put(f"configs/{name}", data={"value": value})

    def states(self) -> list[dict]:
        return [to_camel(s) for s in self._get_all("states")]

    def set_state(self, state: str) -> Any:
        """``start``/``stop``/``restart`` control ZoneMinder; other names apply a run state."""
        if state in ("start", "stop", "restart"):
            return self._api.post(f"server/control/{state}")
        return self._api.post("system/state", data={"state_name": state})

    def servers(self) -> list[dict]:
        return [to_camel(s) for s in self._get_all("servers")]

    def storage(self) -> list[dict]:
        return [to_camel(s) for s in self._get_all("storage")]

