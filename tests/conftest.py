import os
import tempfile
from datetime import datetime, timedelta, timezone
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


@pytest.fixture(autouse=True)
def business_hours_clock(monkeypatch):
    """Make the odd-hour rule independent of when the tests run: the merchant's clock always reads 12:xx.

    Real instants (so payment ages still work), shown in a timezone whose hour is 12 right now.
    Tests of the odd-hour rule itself patch rules._now again.
    """
    from app.screening import rules
    monkeypatch.setattr(rules, '_now', lambda: datetime.now(timezone(timedelta(hours=12 - datetime.now(timezone.utc).hour))))
