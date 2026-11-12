import os
import sys
import tempfile
from pathlib import Path

import pytest

# Tests run offline against the fictional sample provider and a throwaway database,
# unless explicitly marked `live`.
_tmp = tempfile.mkdtemp(prefix="stockiq-test-")
os.environ.setdefault("STOCKIQ_DB_PATH", str(Path(_tmp) / "test.db"))
os.environ.setdefault("STOCKIQ_DATA_DIR", _tmp)  # backups etc. never touch the real data folder
os.environ["STOCKIQ_SESSION_TOKEN"] = "test-token"
os.environ["STOCKIQ_ALLOWED_HOSTS"] = "testserver"  # host name used by FastAPI's TestClient
AUTH = {"X-Analytivest-Token": "test-token"}
if "--live" not in sys.argv:
    os.environ["STOCKIQ_OFFLINE"] = "1"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def pytest_addoption(parser):
    parser.addoption("--live", action="store_true", default=False, help="run tests that call Yahoo Finance")


def pytest_configure(config):
    config.addinivalue_line("markers", "live: calls the real Yahoo Finance endpoints")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--live"):
        return
    skip = pytest.mark.skip(reason="needs --live (network)")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)
