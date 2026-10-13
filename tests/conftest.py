import os
import tempfile
import pytest
from fastapi.testclient import TestClient

@pytest.fixture()
def client(monkeypatch):
    fd, path = tempfile.mkstemp(suffix='.sqlite3')
    os.close(fd)
    monkeypatch.setenv('DATABASE_PATH', path)
    from app import config, db
    object.__setattr__(config.settings, 'database_path', path)
    db.settings = config.settings
    from app.main import app, startup
    startup()
    with TestClient(app) as test_client:
        yield test_client
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
