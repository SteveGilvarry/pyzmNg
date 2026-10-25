# pyzmNg domain context

Verified project facts for writing code: API quirks, platform behavior,
and approaches that already failed. Read before working on the subsystem
it covers. New entries arrive through the self-improvement protocol
(AGENTS.md M5) when a session learns a durable fact the hard way. Entries
carry no personal data, hostnames, or addresses. Each entry cites the
commit hash behind it; the instruction gate checks the hash exists.

## Running against ZoneMinder

- Read the ZM database, configs, and secrets as the ZoneMinder user:
  `sudo -u www-data`. They are not readable by other users.
- ZoneMinder inserts a new event with Frames, AlarmFrames, and MaxScore
  NULL and fills them on zmc's first update. Treat NULL as 0 (aa7896f).
- LastNotifiedAt can come back naive (ZM server local time) or with an
  offset. Compare against datetime.now(last.tzinfo) (657321d).
- On ZM 1.37+, a monitor's Function column is stale: ZM keeps state in
  Capturing, Analysing and Recording. Read and write those (8d6c6f8).
- monitors/alarm status numbers are one higher on ZM 1.36.16 through
  1.36.25 (zmu shifted its states; the API subtracted it again from
  1.36.26). Verified per tag in ZM's MonitorsController (8d6c6f8).
- events/consoleEvents returns {"results": []}, a list, when no monitor has
  events in the interval, and HTTP 500 for a malformed interval (8d6c6f8).
- requests puts the full URL, token included, in HTTPError and
  ConnectionError messages. ZMAPI.request re-raises them redacted; don't
  add a path that raises them raw (16796d9).

## ZoneMinder database

- PyMySQL is not a drop-in for mysql-connector. It has no
  cursor(dictionary=True), its ping takes only reconnect, it returns a zero
  DATETIME as a string, and MySQL 8 caching_sha2_password over TCP without
  TLS needs the cryptography package. Connect through pyzm.zm.db.connect and
  get dict rows from dict_cursor (881dd5c).

## Frame fetch

- A transport failure from ZMAPI.request (read timeout, dropped
  connection, exhausted retries) is a bad frame, not an exception that ends
  the event; frames already fetched survive (5d5e63e).
- requests.exceptions.JSONDecodeError subclasses ValueError. Catch
  RequestException before ValueError or it is matched as the wrong error
  (47186aa).

## ML backends

- OpenCV 5 removed the Darknet importer. Check the version before
  readNet and name the model and a working OpenCV version in the error
  (66e603f).
- A CUDA error during inference used to pin the model to CPU for the life
  of the object, which on a long-running pyzm.serve is permanent. Retry the
  GPU instead (65f83a7).
- The past-detection file is read and written by concurrent hook runs.
  Write to a temp file and os.replace it (46dd7e0).
- There is no label_map config key in the detection pipeline. A
  remap-only shortcut built on it was reverted (8724836).

## Remote gateway (pyzm.serve)

- GatewayUnreachable must escape multi-frame detection, or the caller's
  ml_fallback_local never runs (69ea978).
- Settings the client configures (min_confidence and others) travel with
  each /infer request; the gateway must not override them (4ec4197).
- In multi-worker mode, model_dump_json masks secrets, so workers lost
  auth_password. Pass config through config_to_env/config_from_env
  (2699097).
