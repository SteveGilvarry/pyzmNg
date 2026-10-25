Monitors & Zones
=================

Listing monitors
-----------------

.. code-block:: python

   for m in zm.monitors():
       print(f"Monitor {m.id}: {m.name} ({m.analysing}/{m.recording}) {m.width}x{m.height}")

   # Single monitor
   m = zm.monitor(1)

``monitors()`` returns ``list[Monitor]``. Results are cached after the first
call; pass ``force_reload=True`` to refresh.

What a monitor does is in three fields on ZM 1.37 and newer:
``capturing`` (``"None"``, ``"Ondemand"``, ``"Always"``), ``analysing``
(``"None"``, ``"Always"``) and ``recording`` (``"None"``, ``"OnMotion"``,
``"Always"``). ``function`` is the older ``Function`` column (``"Modect"``,
``"Record"`` and so on). ZM 1.37+ no longer keeps it current, so on those
versions read the three fields instead. On older ZM the three fields are
empty strings and ``function`` is the one to use.

``server_id`` is the ``Servers`` row the monitor runs on in a multi-server
setup, and ``None`` otherwise.

Monitor status
---------------

Each monitor carries a ``status`` object with runtime information:

.. code-block:: python

   m = zm.monitor(1)
   print(m.status.state)         # "Idle", "Alarm", etc.
   print(m.status.fps)           # capture FPS (float)
   print(m.status.analysis_fps)  # analysis FPS (float)
   print(m.status.bandwidth)     # capture bandwidth in bytes (int)
   print(m.status.capturing)     # "None", "Capturing", etc.

Monitor control
----------------

.. code-block:: python

   m = zm.monitor(1)

   # Alarm control
   m.arm()                              # trigger alarm
   m.disarm()                           # cancel alarm
   m.alarm_state()                      # "idle", "prealarm", "alarm", "alert", "tape" or "unknown"
   m.alarm_status()                     # the raw API response, e.g. {"status": 0, "output": 0}

   # Update monitor settings (ZM 1.37+)
   m.update(Analysing="Always", Recording="OnMotion")
   # Older ZM:
   m.update(Function="Modect", Enabled="1")

   # Daemon status
   m.daemon_status()                    # capture daemon (zmc) status

Streaming & snapshot URLs
--------------------------

.. code-block:: python

   m = zm.monitor(1)

   # MJPEG stream
   url = m.streaming_url()                           # protocol=mjpeg (default)
   url = m.streaming_url(maxfps=5, scale=50)         # with extra params

   # Single-frame snapshot
   url = m.snapshot_url()                            # mode=single
   url = m.snapshot_url(scale=50)

``alarm_state()`` turns the status number into a name, including on ZM
1.36.16 through 1.36.25, where the API reports every state one higher than
other versions do. (``SharedMemory.alarm_state()`` in :doc:`zm_system` is a
different thing: it reads the monitor's shared memory on the ZM host.)

.. code-block:: python

   # For a client with no ZM session, such as a browser or media player
   url = m.streaming_url(authenticated=True)

Both URLs are built from the portal URL and ``ZM_PATH_ZMS``, with automatic
path deduplication (e.g. ``/zm`` won't be doubled). ``ZM_PATH_ZMS`` is read
once per client. On a multi-server setup, a monitor on another server gets
that server's address from its ``Servers`` row (protocol, hostname, port and
ZMS path), the way ZM's own web UI builds it.

``authenticated=True`` appends the current auth token, so whatever opens the
URL doesn't need its own ZM login. Tokens expire, so build the URL when you
need it rather than storing it. Without it, the URL is the same as before.

PTZ control
------------

.. code-block:: python

   m = zm.monitor("FrontDoor (Video)")

   if m.controllable:
       # Query what the camera can do
       caps = m.ptz_capabilities()
       print(caps.can_move_con, caps.can_zoom, caps.has_presets)

       # Simple commands — auto-detects the best mode from the control profile
       m.ptz("up")
       m.ptz("stop")
       m.ptz("zoom_in")

       # Move for 2 seconds then auto-stop
       m.ptz("right", stop_after=2.0)

       # Explicit mode override
       m.ptz("left", mode="rel")

       # Presets
       m.ptz("home")
       m.ptz("preset", preset=3)

Supported commands: ``up``, ``down``, ``left``, ``right``, ``up_left``,
``up_right``, ``down_left``, ``down_right``, ``zoom_in``, ``zoom_out``,
``stop``, ``home``, ``preset``.

Modes: ``auto`` (default — picks the best mode supported by the camera's
control profile, preferring continuous > relative > absolute),
``con`` (continuous), ``rel`` (relative), ``abs`` (absolute).

Monitor events
---------------

.. code-block:: python

   m = zm.monitor(1)

   # Query events for this monitor
   recent = m.events(since="6 hours ago", limit=10)
   for ev in recent:
       print(f"Event {ev.id}: {ev.cause} ({ev.length:.1f}s)")

   # Bulk-delete old events for this monitor
   count = m.delete_events(before="1 week ago", limit=500)
   print(f"Deleted {count} events from {m.name}")

Accepts the same filters as the top-level ``zm.events()`` and
``zm.delete_events()`` calls — see :doc:`zm_events` for the full list.

Getting zones
--------------

.. code-block:: python

   m = zm.monitor(1)
   zones = m.get_zones()
   for z in zones:
       print(f"{z.name}: {len(z.points)} points, pattern={z.pattern}")

Zones are used by the ML detector for region-based filtering.
