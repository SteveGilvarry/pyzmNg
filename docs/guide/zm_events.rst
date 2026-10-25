Events & Frames
================

Querying events
----------------

.. code-block:: python

   # Events from the last hour
   events = zm.events(since="1 hour ago", limit=5)
   for ev in events:
       print(f"Event {ev.id}: {ev.cause} ({ev.length:.1f}s, {ev.alarm_frames} alarm frames)")

   # Events for a specific monitor
   events = zm.events(monitor_id=1, since="1 hour ago")

   # Single event
   ev = zm.event(12345)

Filters: ``event_id``, ``monitor_id``, ``since``, ``until``,
``min_alarm_frames``, ``object_only``, ``limit``.

``since`` and ``until`` (and ``before`` in ``delete_events()``) take:

- "N <unit> ago", where the unit is seconds, minutes, hours, days, weeks,
  months or years, singular or plural, or one of ``s``, ``sec``, ``secs``,
  ``min``, ``mins``, ``h``, ``hr``, ``hrs``, ``d``, ``w``, ``wk``, ``wks``,
  ``y``, ``yr``, ``yrs``. "a" or "an" means 1, and the space is optional
  ("2d ago").
- "last week", "last month", "last year"
- "now", "today" (both mean now), "yesterday" (24 hours ago)
- an ISO timestamp such as ``"2024-01-15 10:30:00"`` or ``"2024-01-15"``

Relative times use the clock and timezone of the machine running pyzm, and
ZM compares them in its own timezone, so run both in the same timezone. With
the ``[dates]`` extra installed, dateparser parses these instead (with the
same meaning) and adds forms like "monday" or "January 5".

ZM ignores a time filter it can't read and returns events from any time. So
when a string can't be parsed, pyzm logs a warning and passes it on
unchanged.

Counting events
----------------

.. code-block:: python

   counts = zm.event_counts("1 day")        # {2: 11, 4: 3, 6: 3}
   counts.get(5, 0)                         # monitors with no events aren't in the dict

``event_counts()`` returns how many events started in each monitor within the
interval, from one API call. The interval is a number and a MySQL unit:
``"1 hour"``, ``"1 day"``, ``"1 week"``, ``"1 month"``. Archived events are
left out unless you pass ``include_archived=True``.

``object_only=True`` filters to events that have been tagged by ML
detection (events whose Notes field matches ``"detected"``).

Per-frame metadata
-------------------

.. code-block:: python

   ev = zm.event(12345)
   frames = ev.get_frames()
   for f in frames:
       print(f"Frame {f.frame_id}: type={f.type} score={f.score} delta={f.delta:.2f}s")

   # Find the highest-scoring frame
   best = max(frames, key=lambda f: f.score)
   print(f"Best frame: {best.frame_id} (score={best.score})")

``get_frames()`` returns ``list[Frame]`` with per-frame ``Score``,
``Type`` (Normal/Alarm/Bulk), and ``Delta`` (seconds since event start).

Event methods
--------------

.. code-block:: python

   ev = zm.event(12345)

   # Update the Notes field
   ev.update_notes("person detected at front door")

   # Tag with detected object labels (requires ZM >= 1.37.44, DB access)
   ev.tag(["person", "car"])

   # Get the filesystem path (requires DB access)
   path = ev.path()
   # e.g. "/var/cache/zoneminder/events/1/2024-01-15/12345"

   # Save detection artifacts to the event directory
   annotated = result.annotate()
   ev.save_objdetect(annotated, result.to_dict())
   # Writes objdetect.jpg and objects.json to ev.path()
   # Use path_override="..." to write to a different directory

``tag()``, ``path()``, and ``save_objdetect()`` (when no
``path_override`` is given) require a direct database connection and a
MySQL driver (``pip install "pyzm[db]"``).  By default, credentials are
read from ``zm.conf``, which pyzm finds through the client's ``conf_path``,
the ``PYZM_CONFPATH`` env var, or in ``/etc/zm``, ``/config`` or
``/etc/zoneminder``.  If it isn't readable, pass ``db_user``,
``db_password``, etc. when creating the client.  See :doc:`zm_client` for
details.

   # Extract frames as numpy arrays (requires pyzm[ml])
   frames, dims = ev.extract_frames(stream_config=StreamConfig(resize=800))
   # frames: list of (frame_id, numpy_array) tuples
   # dims: {"original": (h, w), "resized": (rh, rw) or None}

   # Delete
   ev.delete()

Bulk operations
----------------

.. code-block:: python

   # Bulk delete events matching filters
   count = zm.delete_events(monitor_id=1, before="7 days ago", limit=500)
   print(f"Deleted {count} events")

   # OOP: query events scoped to a monitor
   m = zm.monitor(1)
   recent = m.events(since="6 hours ago", limit=10)

   # OOP: bulk-delete old events for a monitor
   count = m.delete_events(before="1 week ago", limit=500)
   print(f"Deleted {count} events from {m.name}")

``delete_events()`` filters: ``monitor_id``, ``before``,
``min_alarm_frames``, ``limit``.

