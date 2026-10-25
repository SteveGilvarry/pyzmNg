"""Common test fixtures for pyzm v2 test suite."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest

from pyzm.models.config import (
    DetectorConfig,
    MatchStrategy,
    ModelConfig,
    ModelFramework,
    ModelType,
    Processor,
    ZMClientConfig,
)
from pyzm.models.detection import BBox, Detection, DetectionResult
from pyzm.models.zm import Zone


# ---------------------------------------------------------------------------
# Markers
# ---------------------------------------------------------------------------

def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: marks tests requiring optional deps (cv2, shapely, numpy)",
    )
    config.addinivalue_line(
        "markers",
        "e2e: end-to-end tests requiring real models and images on disk",
    )
    config.addinivalue_line(
        "markers",
        "serve: tests that start a pyzm.serve subprocess",
    )
    config.addinivalue_line(
        "markers",
        "zm_e2e: tests requiring a live ZoneMinder instance",
    )
    config.addinivalue_line(
        "markers",
        "zm_e2e_write: zm_e2e tests that mutate ZM state (opt-in via ZM_E2E_WRITE=1)",
    )


# ---------------------------------------------------------------------------
# Fixtures -- images
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_image():
    """A small 100x100x3 numpy array (uint8) for testing."""
    try:
        import numpy as np
        return np.zeros((100, 100, 3), dtype=np.uint8)
    except ImportError:
        pytest.skip("numpy not installed")


# ---------------------------------------------------------------------------
# Fixtures -- config
# ---------------------------------------------------------------------------

@pytest.fixture
def zm_client_config() -> ZMClientConfig:
    """A ZMClientConfig with test values."""
    return ZMClientConfig(
        api_url="https://zm.example.com/zm/api",
        user="admin",
        password="secret",
        verify_ssl=False,
        timeout=10,
    )


@pytest.fixture
def detector_config() -> DetectorConfig:
    """A DetectorConfig with a single YOLO model config."""
    mc = ModelConfig(
        name="yolov4-test",
        enabled=True,
        type=ModelType.OBJECT,
        framework=ModelFramework.OPENCV,
        processor=Processor.CPU,
        weights="/tmp/yolov4.weights",
        config="/tmp/yolov4.cfg",
        labels="/tmp/coco.names",
        min_confidence=0.5,
        pattern="(person|car|dog)",
        model_width=416,
        model_height=416,
    )
    return DetectorConfig(
        models=[mc],
        match_strategy=MatchStrategy.FIRST,
    )


# ---------------------------------------------------------------------------
# Fixtures -- detections
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_detections() -> list[Detection]:
    """A list of Detection objects for testing."""
    return [
        Detection(
            label="person",
            confidence=0.97,
            bbox=BBox(x1=10, y1=20, x2=50, y2=80),
            model_name="yolov4",
            detection_type="object",
        ),
        Detection(
            label="car",
            confidence=0.85,
            bbox=BBox(x1=60, y1=30, x2=90, y2=70),
            model_name="yolov4",
            detection_type="object",
        ),
        Detection(
            label="dog",
            confidence=0.72,
            bbox=BBox(x1=5, y1=50, x2=30, y2=95),
            model_name="yolov4",
            detection_type="object",
        ),
    ]


# ---------------------------------------------------------------------------
# Fixtures -- zones
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_zones() -> list[Zone]:
    """A list of Zone objects for testing."""
    return [
        Zone(
            name="driveway",
            points=[(0, 0), (100, 0), (100, 100), (0, 100)],
            pattern="(person|car)",
        ),
        Zone(
            name="garden",
            points=[(50, 50), (200, 50), (200, 200), (50, 200)],
            pattern="(dog|cat)",
        ),
    ]


# ---------------------------------------------------------------------------
# Fixtures -- MySQL drivers
# ---------------------------------------------------------------------------
# pyzm talks to the ZM database through mysql-connector-python or PyMySQL.
# These install stand-in driver modules in sys.modules so tests run the same
# whichever real driver (if any) the test machine has.

class FakePyMySQLConnection:
    """Stand-in for ``pymysql.connections.Connection``.

    Method signatures match PyMySQL's, so a mysql-connector-only argument
    (``cursor(dictionary=True)``, ``ping(attempts=...)``) raises TypeError
    here the way it does against the real driver.
    """

    __module__ = "pymysql.connections"

    def __init__(self) -> None:
        self.cursor_obj = MagicMock()
        self.cursor_classes: list = []
        self.closed = False

    def cursor(self, cursor=None):
        self.cursor_classes.append(cursor)
        return self.cursor_obj

    def ping(self, reconnect=False):
        if self.closed:
            raise sys.modules["pymysql"].Error("Already closed")

    def commit(self):
        pass

    def close(self):
        self.closed = True


def _hidden_mysql_connector() -> dict:
    return {"mysql": None, "mysql.connector": None}


def fake_pymysql_modules() -> dict:
    """sys.modules entries for a fake PyMySQL, with mysql-connector hidden."""
    mod = types.ModuleType("pymysql")
    mod.Error = type("Error", (Exception,), {})
    mod.connect = MagicMock(return_value=FakePyMySQLConnection())
    cursors = types.ModuleType("pymysql.cursors")
    cursors.DictCursor = type("DictCursor", (), {})
    mod.cursors = cursors
    return {"pymysql": mod, "pymysql.cursors": cursors, **_hidden_mysql_connector()}


def fake_mysql_connector_modules() -> dict:
    """sys.modules entries for a fake mysql-connector-python."""
    pkg = types.ModuleType("mysql")
    mod = types.ModuleType("mysql.connector")
    mod.Error = type("Error", (Exception,), {})
    mod.connect = MagicMock(return_value=MagicMock())
    pkg.connector = mod
    return {"mysql": pkg, "mysql.connector": mod}


@pytest.fixture
def fake_pymysql(monkeypatch):
    """PyMySQL installed, mysql-connector not (a fresh ``pyzm[db]`` install)."""
    modules = fake_pymysql_modules()
    for name, mod in modules.items():
        monkeypatch.setitem(sys.modules, name, mod)
    return modules["pymysql"]


@pytest.fixture
def fake_mysql_connector(monkeypatch):
    """mysql-connector installed (an install upgraded from pyzm <= 2.5)."""
    modules = fake_mysql_connector_modules()
    for name, mod in modules.items():
        monkeypatch.setitem(sys.modules, name, mod)
    return modules["mysql.connector"]


@pytest.fixture
def mock_connect(fake_mysql_connector):
    """``connect`` of the fake mysql-connector."""
    return fake_mysql_connector.connect


@pytest.fixture
def no_mysql_driver(monkeypatch):
    """Neither MySQL driver importable (a base ``pip install pyzm``)."""
    for name in ("pymysql", "pymysql.cursors", "mysql", "mysql.connector"):
        monkeypatch.setitem(sys.modules, name, None)
