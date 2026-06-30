"""
Testes de integração para as funções de eventos do repo.py.

Cobre: list_events, create_event, count_events_for_tenant,
       e os filtros event_id em get_invitees / count_invitees_by_response.

Como rodar (dentro do container):
    pytest tests/test_repo_events.py -v -m integration
"""
import os
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

sys.path.insert(0, "/app")
import repo

TEST_DB = "rsvp_test"


def _creds():
    user = os.environ.get("TEST_DB_USER") or os.environ.get("DB_USER", "root")
    pw   = os.environ.get("TEST_DB_PASSWORD") or os.environ.get("DB_PASSWORD", "")
    host = os.environ.get("TEST_DB_HOST") or os.environ.get("DB_HOST", "db")
    return user, pw, host


def _mysql_available():
    try:
        user, pw, host = _creds()
        eng = create_engine(
            f"mysql+pymysql://{user}:{pw}@{host}/?charset=utf8mb4",
            poolclass=NullPool, future=True,
        )
        with eng.connect() as c:
            c.execute(text("SELECT 1"))
        eng.dispose()
        return True
    except Exception:
        return False


def _ensure_test_db():
    """Cria rsvp_test se não existir e aplica migrations."""
    user, pw, host = _creds()
    admin_eng = create_engine(
        f"mysql+pymysql://{user}:{pw}@{host}/?charset=utf8mb4",
        poolclass=NullPool, future=True,
    )
    with admin_eng.connect() as conn:
        conn.execute(text(
            f"CREATE DATABASE IF NOT EXISTS {TEST_DB} "
            "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        ))
    admin_eng.dispose()

    env = {
        **os.environ,
        "DB_NAME": TEST_DB,
        "DB_HOST": host,
        "DB_USER": user,
        "DB_PASSWORD": pw,
    }
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        capture_output=True, text=True,
        cwd="/app", env=env,
    )
    assert result.returncode == 0, (
        f"alembic upgrade head falhou.\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
    )


@pytest.fixture
def db_conn():
    if not _mysql_available():
        pytest.skip("MySQL not available")
    _ensure_test_db()
    user, pw, host = _creds()
    eng = create_engine(
        f"mysql+pymysql://{user}:{pw}@{host}/{TEST_DB}?charset=utf8mb4",
        poolclass=NullPool, future=True,
    )
    with eng.connect() as conn:
        yield conn
    eng.dispose()


@pytest.fixture
def tenant_factory(db_conn):
    created = []

    def _factory(name="TestTenant"):
        tenant_id = repo.create_tenant(db_conn, name)
        event_id = repo.create_default_event(db_conn, tenant_id, name)
        db_conn.commit()
        created.append(tenant_id)
        return {"tenant_id": tenant_id, "event_id": event_id}

    yield _factory

    # cleanup: delete in reverse dependency order
    for tid in created:
        db_conn.execute(text("DELETE FROM invitees WHERE tenant_id = :tid"), {"tid": tid})
        db_conn.execute(text("DELETE FROM events WHERE tenant_id = :tid"), {"tid": tid})
        db_conn.execute(text("DELETE FROM users WHERE tenant_id = :tid"), {"tid": tid})
        db_conn.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
    db_conn.commit()


# ── testes ────────────────────────────────────────────────────────────────────

@pytest.mark.integration
def test_list_events_returns_only_tenant_events(db_conn, tenant_factory):
    t1 = tenant_factory(name="T1")
    t2 = tenant_factory(name="T2")
    # cada tenant_factory já cria 1 evento default
    events_t1 = repo.list_events(db_conn, t1["tenant_id"])
    events_t2 = repo.list_events(db_conn, t2["tenant_id"])
    assert len(events_t1) == 1
    assert len(events_t2) == 1
    assert events_t1[0]["tenant_id"] == t1["tenant_id"]


@pytest.mark.integration
def test_create_event_increments_count(db_conn, tenant_factory):
    t = tenant_factory(name="T3")
    tid = t["tenant_id"]
    before = repo.count_events_for_tenant(db_conn, tid)
    repo.create_event(db_conn, tid, title="Festa 2", owner_user_id=None)
    db_conn.commit()
    after = repo.count_events_for_tenant(db_conn, tid)
    assert after == before + 1


@pytest.mark.integration
def test_create_event_returns_new_id(db_conn, tenant_factory):
    t = tenant_factory(name="T4")
    eid = repo.create_event(db_conn, t["tenant_id"], title="Teste", owner_user_id=None)
    db_conn.commit()
    assert isinstance(eid, int) and eid > 0


@pytest.mark.integration
def test_set_and_get_event_theme(db_conn, tenant_factory):
    t = tenant_factory(name="TTheme")
    tid = t["tenant_id"]
    eid = t["event_id"]
    assert repo.get_event_theme(db_conn, tid, eid) == "default"
    repo.set_event_theme(db_conn, tid, eid, "girl")
    db_conn.commit()
    assert repo.get_event_theme(db_conn, tid, eid) == "girl"
    repo.set_event_theme(db_conn, tid, eid, "boy")
    db_conn.commit()
    assert repo.get_event_theme(db_conn, tid, eid) == "boy"


@pytest.mark.integration
def test_set_event_theme_rejects_invalid(db_conn, tenant_factory):
    t = tenant_factory(name="TInvalid")
    with pytest.raises(ValueError):
        repo.set_event_theme(db_conn, t["tenant_id"], t["event_id"], "purple")
