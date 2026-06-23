"""
Teste de integração — Fase 5C-3: fluxo completo de new tenant via HTTP.

Usa o Flask test client com um engine real apontando para rsvp_test,
com SKIP_EMAIL_VERIFICATION=true.

Rodar dentro do container:
    pytest -m integration -v
"""
import os
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

TEST_DB = "rsvp_test"


def _creds() -> tuple[str, str, str]:
    user = os.environ.get("TEST_DB_USER") or os.environ.get("DB_USER", "root")
    password = os.environ.get("TEST_DB_PASSWORD") or os.environ.get("DB_PASSWORD", "")
    host = os.environ.get("TEST_DB_HOST") or os.environ.get("DB_HOST", "db")
    return user, password, host


def _mysql_available() -> bool:
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


def _run_alembic(*args: str) -> subprocess.CompletedProcess:
    user, pw, host = _creds()
    env = {
        **os.environ,
        "DB_NAME": TEST_DB,
        "DB_HOST": host,
        "DB_USER": user,
        "DB_PASSWORD": pw,
    }
    return subprocess.run(
        ["alembic", *args],
        capture_output=True,
        text=True,
        cwd="/app",
        env=env,
    )


@pytest.fixture(scope="module")
def integration_client():
    """
    Flask test client apontado para rsvp_test (banco de integração).
    Cria o banco, aplica migrations e restaura tudo ao final.
    SKIP_EMAIL_VERIFICATION=true para evitar envio de email.
    """
    if not _mysql_available():
        pytest.skip("MySQL não disponível — rode dentro do container Docker")

    user, pw, host = _creds()

    # Cria banco de teste limpo
    admin_engine = create_engine(
        f"mysql+pymysql://{user}:{pw}@{host}/?charset=utf8mb4",
        poolclass=NullPool, future=True,
    )
    with admin_engine.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB}"))
        conn.execute(text(
            f"CREATE DATABASE {TEST_DB} "
            "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        ))
    admin_engine.dispose()

    # Aplica migrations
    result = _run_alembic("upgrade", "head")
    assert result.returncode == 0, (
        f"Alembic upgrade falhou.\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )

    # Engine real para rsvp_test
    real_engine = create_engine(
        f"mysql+pymysql://{user}:{pw}@{host}/{TEST_DB}?charset=utf8mb4",
        poolclass=NullPool, future=True,
    )

    import app as app_module
    original_engine = app_module.engine
    app_module.engine = real_engine

    os.environ["SKIP_EMAIL_VERIFICATION"] = "true"

    flask_app = app_module.app
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False

    with flask_app.test_client() as client:
        yield client

    # Teardown
    app_module.engine = original_engine
    os.environ.pop("SKIP_EMAIL_VERIFICATION", None)
    real_engine.dispose()

    admin_engine2 = create_engine(
        f"mysql+pymysql://{user}:{pw}@{host}/?charset=utf8mb4",
        poolclass=NullPool, future=True,
    )
    with admin_engine2.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB}"))
    admin_engine2.dispose()


@pytest.mark.integration
def test_new_tenant_first_login(integration_client):
    """
    Fluxo completo via HTTP: signup → login → GET /admin/respostas (200).
    Usa banco real rsvp_test com SKIP_EMAIL_VERIFICATION=true.
    """
    email = "integration_flow_5c3@test.com"
    password = "Integr@Test99"

    # Limpa usuário se sobrou de run anterior
    import app as app_module
    with app_module.engine.connect() as conn:
        existing = conn.execute(
            text("SELECT id FROM users WHERE email = :e"), {"e": email}
        ).fetchone()
        if existing:
            conn.execute(
                text("DELETE FROM users WHERE email = :e"), {"e": email}
            )
            conn.commit()

    # 1. Signup
    r = integration_client.post("/signup", data={
        "nome_anfitriao": "Test Host 5C3",
        "email": email,
        "password": password,
        "confirm_password": password,
        "accept_terms": "1",
    }, follow_redirects=True)
    assert r.status_code == 200, f"Signup falhou com status {r.status_code}"

    # 2. Login
    r = integration_client.post("/login", data={
        "email": email,
        "password": password,
    }, follow_redirects=True)
    assert r.status_code == 200, f"Login falhou com status {r.status_code}"
    assert b"respostas" in r.data.lower() or b"convidados" in r.data.lower(), (
        "Após login esperava chegar em /admin/respostas mas o conteúdo não bate"
    )
