"""Install requirements declared in setup.py (#85)."""

from __future__ import annotations

import os
import runpy
import sys
import types
from unittest.mock import MagicMock, patch

_SETUP = os.path.join(os.path.dirname(os.path.dirname(__file__)), "setup.py")


def _setup_kwargs() -> dict:
    # A stand-in setuptools: Python 3.12+ venvs don't ship the real one.
    fake = types.ModuleType("setuptools")
    fake.setup = MagicMock()
    fake.find_packages = MagicMock(return_value=[])
    with patch.dict(sys.modules, {"setuptools": fake}):
        runpy.run_path(_SETUP)
    return fake.setup.call_args.kwargs


def _names(reqs: list[str]) -> set[str]:
    return {r.split("[")[0].split(">")[0].split("=")[0].strip().lower() for r in reqs}


def test_base_install_has_no_mysql_driver():
    assert not _names(_setup_kwargs()["install_requires"]) & {"mysql-connector-python", "pymysql"}


def test_db_extra_installs_pymysql():
    assert _names(_setup_kwargs()["extras_require"]["db"]) == {"pymysql"}


def test_on_box_extras_include_db_driver():
    """ES depends on pyzm[ml]; tagging and DB logging must keep working there."""
    extras = _setup_kwargs()["extras_require"]
    for name in ("ml", "full"):
        assert "pymysql" in _names(extras[name]), name
