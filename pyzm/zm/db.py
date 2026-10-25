"""Direct MySQL connection to the ZoneMinder database.

Reads credentials from ``zm.conf`` (and ``conf.d/*.conf``) — the same files
that ZM itself uses.  The directory is resolved by :func:`_resolve_conf_path`:
an explicit ``conf_path`` or the ``PYZM_CONFPATH`` env var wins, otherwise a
few well-known locations are probed (handles containerized ZM, which keeps
config under ``/config``).  Explicit credential overrides take precedence.

The driver is optional (``pip install "pyzm[db]"`` installs PyMySQL).  When
mysql-connector-python is installed, as it is on most installs upgraded from
pyzm 2.5.4 and older, it is used instead.
"""

from __future__ import annotations

import configparser
import glob
import logging
import os

logger = logging.getLogger("pyzm.zm")

_CONF_PATH = os.environ.get("PYZM_CONFPATH", "/etc/zm")

# Well-known directories to probe for zm.conf, in order, when neither an
# explicit conf_path nor PYZM_CONFPATH is provided. /etc/zm is the default
# install location; /config is the common container layout; /etc/zoneminder
# is used by some distro packages.
_CONF_SEARCH_PATHS = ("/etc/zm", "/config", "/etc/zoneminder")

# Seconds to wait for the DB server to accept a connection. Without it a dead
# DB host stalls detection and logging for the OS TCP timeout.
_CONNECT_TIMEOUT = 10

_DEFAULT_PORT = 3306

_NO_DRIVER_HINT = (
    'No MySQL driver installed, DB access unavailable. '
    'Install it with: pip install "pyzm[db]"'
)


def _resolve_conf_path(conf_path: str | None = None) -> str:
    """Return the directory to read ZM config from.

    Priority: explicit ``conf_path`` argument, then the ``PYZM_CONFPATH`` env
    var, then auto-discovery across :data:`_CONF_SEARCH_PATHS` (the first that
    actually contains a ``zm.conf``). Falls back to ``/etc/zm`` when nothing is
    found, preserving prior behaviour and its warnings.
    """
    if conf_path:
        return conf_path
    env = os.environ.get("PYZM_CONFPATH")
    if env:
        return env
    for candidate in _CONF_SEARCH_PATHS:
        if os.path.exists(os.path.join(candidate, "zm.conf")):
            logger.debug("Auto-discovered ZM config at %s", candidate)
            return candidate
    return _CONF_SEARCH_PATHS[0]


def _read_zm_conf(conf_path: str = _CONF_PATH) -> dict[str, str]:
    """Parse ZM config files and return DB credentials."""
    files = sorted(glob.glob(os.path.join(conf_path, "conf.d", "*.conf")))
    files.insert(0, os.path.join(conf_path, "zm.conf"))

    parser = configparser.ConfigParser(
        interpolation=None, inline_comment_prefixes=("#",)
    )
    for f in files:
        if not os.path.exists(f):
            continue
        with open(f) as fh:
            parser.read_string("[zm_root]\n" + fh.read())

    section = parser["zm_root"] if parser.has_section("zm_root") else {}
    return {
        "user": section.get("ZM_DB_USER", "zmuser"),
        "password": section.get("ZM_DB_PASS", "zmpass"),
        "host": section.get("ZM_DB_HOST", "localhost"),
        "database": section.get("ZM_DB_NAME", "zm"),
    }


def _load_driver():
    """Return the MySQL driver module, or ``None`` when none is installed."""
    # mysql-connector first: installs upgraded from pyzm <= 2.5.4 have it, and
    # keeping them on it means an upgrade never changes driver behavior.
    try:
        import mysql.connector
        return mysql.connector
    except ImportError:
        pass
    try:
        import pymysql
        return pymysql
    except ImportError:
        return None


def driver_available() -> bool:
    """Whether a MySQL driver is installed."""
    return _load_driver() is not None


def connect(host: str, user: str, password: str, database: str, *, quiet: bool = False):
    """Open a connection to the ZM database, or return ``None``.

    *host* takes ZM_DB_HOST syntax: ``host``, ``host:port`` or
    ``host:/path/to/socket``.  Failures are logged at WARNING, or at DEBUG
    with ``quiet=True`` (the log handler uses that, since it can't log
    through itself).  No exception escapes.
    """
    log = logger.debug if quiet else logger.warning
    driver = _load_driver()
    if driver is None:
        log(_NO_DRIVER_HINT)
        return None

    kw: dict = {"user": user, "password": password, "database": database}
    where = host
    if ":" in host:
        host, suffix = host.split(":", 1)
        if suffix.startswith("/"):
            kw["unix_socket"] = suffix
        else:
            try:
                kw["port"] = int(suffix)
            except ValueError:
                log("Invalid port in db_host %r, using default %d", where, _DEFAULT_PORT)
                kw["port"] = _DEFAULT_PORT
            kw["host"] = host
    else:
        kw["host"] = host
        kw["port"] = _DEFAULT_PORT
    if driver.__name__ == "pymysql":
        kw["connect_timeout"] = _CONNECT_TIMEOUT
    else:
        kw["connection_timeout"] = _CONNECT_TIMEOUT

    try:
        return driver.connect(**kw)
    except Exception as exc:  # driver errors, socket errors, PyMySQL's RuntimeError for missing cryptography
        log("DB connect to %s failed: %s", where, exc)
        return None


def dict_cursor(conn):
    """Return a cursor on *conn* whose rows are dicts, for either driver."""
    if type(conn).__module__.startswith("pymysql"):
        import pymysql.cursors
        return conn.cursor(pymysql.cursors.DictCursor)
    return conn.cursor(dictionary=True)


def get_zm_db(
    db_user: str | None = None,
    db_password: str | None = None,
    db_host: str | None = None,
    db_name: str | None = None,
    conf_path: str | None = None,
):
    """Return a connection to the ZM database, or ``None``.

    The connection comes from whichever driver is installed (see the module
    docstring); use :func:`dict_cursor` for dict rows.

    Merge strategy: always try to read zm.conf first. If it's unreadable
    (permission denied, missing), log a warning and continue. Then overlay
    any explicit values — explicit values win over zm.conf values. Final
    fallback for host is ``"localhost"``, for db name is ``"zm"``.
    """
    if not driver_available():
        logger.warning(_NO_DRIVER_HINT)
        return None

    # Start with zm.conf values (best-effort)
    has_explicit = any(v is not None for v in [db_user, db_password, db_host, db_name])
    try:
        creds = _read_zm_conf(_resolve_conf_path(conf_path))
    except (PermissionError, OSError) as exc:
        if has_explicit:
            logger.debug("Could not read zm.conf: %s (using explicit credentials)", exc)
        else:
            logger.warning("Could not read zm.conf: %s", exc)
        creds = {"user": "zmuser", "password": "zmpass", "host": "localhost", "database": "zm"}

    # Overlay explicit overrides
    if db_user is not None:
        creds["user"] = db_user
    if db_password is not None:
        creds["password"] = db_password
    if db_host is not None:
        creds["host"] = db_host
    if db_name is not None:
        creds["database"] = db_name

    return connect(creds["host"], creds["user"], creds["password"], creds["database"])
