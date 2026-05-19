import os
import sys
import tempfile

# Set env vars before any app imports so config.py picks them up
_tmpdir = tempfile.mkdtemp(prefix="awg_test_")
_awg_conf = f"{_tmpdir}/awg0.conf"
os.environ.update(
    {
        "MOCK_AWG": "true",
        "ADMIN_TOKEN": "test-token",
        "ADMIN_USERNAME": "admin",
        "ADMIN_PASSWORD": "password",
        "CLIENTS_DIR": f"{_tmpdir}/clients",
        "DB_PATH": f"{_tmpdir}/panel.db",
        "SERVERS_PATH": f"{_tmpdir}/servers.json",
        "LOCAL_SERVER_PATH": f"{_tmpdir}/local-server.json",
        "ORDERS_PATH": f"{_tmpdir}/orders.json",
        "AWG_CONFIG_PATH": _awg_conf,
        "AWG_CONTAINER_CONFIG_PATH": _awg_conf,
        "SERVER_ENDPOINT": "1.2.3.4:51820",
        "WEBHOOK_URL": "",
        "WEBHOOK_SECRET": "",
    }
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient
from app.main import app  # noqa: E402 — must come after env setup


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def auth():
    return {"Authorization": "Bearer test-token"}


@pytest.fixture
def clean_client():
    """Fresh TestClient with no cookies — for testing unauthenticated requests."""
    with TestClient(app, cookies={}) as c:
        yield c
