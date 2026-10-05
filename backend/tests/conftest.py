import os
import sys
import tempfile
from pathlib import Path

# Isolated config BEFORE the app is imported (never touch data/app.db).
_tmp = tempfile.mkdtemp(prefix="pw-tests-")
os.environ.update({
    "DATABASE_URL": f"sqlite:///{_tmp}/lifespan.db", "SEED_ON_START": "false", "FORCE_MOCK_LLM": "true",
    "LLM_PROVIDER": "mock", "LLM_RETRY_BACKOFF_SECONDS": "0", "APP_ENV": "test", "LOG_LEVEL": "WARNING",
    "FAULT_INJECTION_ENABLED": "false", "SIMULATE_LLM_OUTAGE": "false", "BCRYPT_ROUNDS": "4",
})
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.db.seed_data import seed_database
from app.main import app
from app.policy.loader import load_policy


@pytest.fixture(scope="session")
def policy():
    return load_policy(str(backend_dir.parent / "policy" / "privacy_policy_v1.yaml"))


@pytest.fixture(autouse=True)
def _reset_flags():
    settings.FAULT_INJECTION_ENABLED = False
    settings.SIMULATE_LLM_OUTAGE = False
    settings.FORCE_MOCK_LLM = True
    yield


@pytest.fixture(scope="session")
def _engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture
def db_session(_engine, policy):
    Session = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
    session = Session()
    seed_database(session, force_reset=True)
    yield session
    session.close()


@pytest.fixture
def client(db_session):
    def override():
        yield db_session
    app.dependency_overrides[get_db] = override
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def auth(client):
    return {
        "analyst": _login(client, "alex.analyst", "analyst_password123!"),
        "approver": _login(client, "jordan.approver", "approver_password123!"),
        "approver2": _login(client, "morgan.approver", "approver_password123!"),
        "auditor": _login(client, "sam.auditor", "auditor_password123!"),
    }
