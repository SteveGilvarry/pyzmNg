"""Build pyzm models from zm-api (``/api/v3``) JSON.

zm-api returns flat snake_case objects with typed values and UTC
timestamps.  pyzm's models, and the plain dicts some ZMClient methods
return, use the v2 shapes: CamelCase keys and naive local timestamps.
These helpers convert between the two so callers see the same objects on
either backend.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from pyzm.models.zm import Event, Frame, Monitor, MonitorStatus, PTZCapabilities

if TYPE_CHECKING:
    from pyzm.client import ZMClient

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")

# Monitor fields zm-api types as strings, so digit-only values stay strings.
_STRING_FIELDS = frozenset({
    "name", "notes", "device", "path", "second_path", "sub_path", "port",
    "host", "user", "pass", "method", "options", "protocol", "triggers",
    "linked_monitors", "event_prefix", "label_format", "control_device",
    "control_address", "onvif_url", "onvif_username", "onvif_password",
})


def to_camel(data: dict) -> dict:
    """``{"default_value": 1}`` -> ``{"DefaultValue": 1}`` (v2 key style)."""
    return {
        "".join(part.capitalize() for part in k.split("_")): v
        for k, v in data.items()
    }


def to_snake(name: str) -> str:
    """``"ControlId"`` -> ``"control_id"`` (zm-api field style)."""
    return _CAMEL_BOUNDARY.sub("_", name).lower()


def local_naive(val: str | None) -> datetime | None:
    """Parse a zm-api UTC timestamp into naive local time, as v2 returns.

    Local means this process's timezone, which matches ZoneMinder's when
    pyzm runs on the ZM host.
    """
    if not val:
        return None
    try:
        dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone().replace(tzinfo=None)


def utc_iso(time_str: str) -> str | None:
    """Human time (``"1 hour ago"``) -> UTC ISO-8601 for zm-api filters."""
    import dateparser

    dt = dateparser.parse(time_str)
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.astimezone()  # naive means local time
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def monitor_update_body(fields: dict[str, Any]) -> dict[str, Any]:
    """v2-style monitor fields (``Enabled="1"``) -> zm-api PATCH body (``enabled: 1``)."""
    body: dict[str, Any] = {}
    for key, val in fields.items():
        name = to_snake(key)
        if isinstance(val, str) and name not in _STRING_FIELDS and val.lstrip("-").isdigit():
            val = int(val)
        body[name] = val
    return body


def _float(val: Any) -> float:
    try:
        return float(val or 0)
    except (TypeError, ValueError):
        return 0.0


def monitor_from_v3(
    data: dict, status: dict | None = None, client: ZMClient | None = None,
) -> Monitor:
    """Build a Monitor from ``MonitorResponse`` plus optional ``MonitorStatusResponse``."""
    st = status or {}
    control_id = data.get("control_id")
    return Monitor(
        id=int(data.get("id", 0)),
        name=data.get("name", ""),
        function=data.get("function", ""),
        enabled=bool(data.get("enabled")),
        width=int(data.get("width") or 0),
        height=int(data.get("height") or 0),
        type=data.get("type", ""),
        controllable=bool(data.get("controllable")),
        control_id=int(control_id) if control_id else None,
        status=MonitorStatus(
            state=st.get("status", ""),
            fps=_float(st.get("capture_fps")),
            analysis_fps=_float(st.get("analysis_fps")),
            bandwidth=int(st.get("capture_bandwidth") or 0),
            capturing=data.get("capturing", "None"),
            _raw=st,
        ),
        _raw=data,
        _client=client,
    )


def event_from_v3(data: dict, client: ZMClient | None = None) -> Event:
    """Build an Event from ``EventResponse``.

    zm-api does not return MaxScoreFrameId or a storage path, so those
    stay ``None`` / empty.
    """
    return Event(
        id=int(data.get("id", 0)),
        name=data.get("name", ""),
        monitor_id=int(data.get("monitor_id", 0)),
        cause=data.get("cause") or "",
        notes=data.get("notes") or "",
        start_time=local_naive(data.get("start_date_time")),
        end_time=local_naive(data.get("end_date_time")),
        length=_float(data.get("length")),
        frames=int(data.get("frames") or 0),
        alarm_frames=int(data.get("alarm_frames") or 0),
        max_score=int(data.get("max_score") or 0),
        max_score_frame_id=None,
        storage_path="",
        _raw=data,
        _client=client,
    )


def frame_from_v3(data: dict, event_id: int) -> Frame:
    """Build a Frame from ``FrameResponse`` (``delta`` arrives as a string)."""
    return Frame(
        frame_id=int(data.get("frame_id", 0)),
        event_id=int(data.get("event_id", event_id)),
        type=data.get("type", ""),
        score=int(data.get("score") or 0),
        delta=_float(data.get("delta")),
        _raw=data,
    )


def ptz_from_v3(data: dict) -> PTZCapabilities:
    """Build PTZCapabilities from ``ControlResponse`` (0/1 integer flags)."""
    caps = PTZCapabilities.from_api_dict(
        {k: str(v) if v is not None else v for k, v in to_camel(data).items()}
    )
    caps._raw = data
    return caps
