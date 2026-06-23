"""
Testes de integração — migration 0001 (schema SaaS multi-tenant).

Executados contra um banco rsvp_test DEDICADO E VAZIO, criado
dinamicamente neste módulo. O banco rsvp_db (dev) nunca é tocado.

Como rodar (dentro do container):
    pytest -m integration -v

Fora do container (se MySQL estiver acessível):
    DB_HOST=localhost pytest -m integration -v
"""
import os
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

TEST_DB = "rsvp_test"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _creds() -> tuple[str, str, str]:
    """
    Retorna (user, password, host) lendo TEST_DB_* primeiro.

    O conftest.py dos testes unitários faz os.environ.update() e sobrescreve
    DB_USER/DB_PASSWORD/DB_HOST com valores falsos. TEST_DB_* não é tocado por
    ele, portanto é o canal seguro para credenciais reais nos testes de integração.
    """
    user = os.environ.get("TEST_DB_USER") or os.environ.get("DB_USER", "root")
    password = os.environ.get("TEST_DB_PASSWORD") or os.environ.get("DB_PASSWORD", "")
    host = os.environ.get("TEST_DB_HOST") or os.environ.get("DB_HOST", "db")
    return user, password, host


def _admin_engine():
    """Conexão sem banco específico (para CREATE/DROP DATABASE)."""
    user, password, host = _creds()
    url = f"mysql+pymysql://{user}:{password}@{host}/?charset=utf8mb4"
    return create_engine(url, poolclass=NullPool, future=True)


def _test_engine():
    """Conexão com rsvp_test."""
    user, password, host = _creds()
    url = f"mysql+pymysql://{user}:{password}@{host}/{TEST_DB}?charset=utf8mb4"
    return create_engine(url, poolclass=NullPool, future=True)


def _mysql_available() -> bool:
    try:
        with _admin_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def _run_alembic(*args: str) -> subprocess.CompletedProcess:
    """
    Roda alembic apontando para rsvp_test.

    Usa o executável 'alembic' (não python -m alembic, pois o pacote não tem
    __main__). Sobrescreve DB_* com as credenciais reais (TEST_DB_*) para que
    alembic/env.py não herde os valores falsos que o conftest.py injeta.
    """
    user, password, host = _creds()
    env = {
        **os.environ,
        "DB_NAME": TEST_DB,
        "DB_HOST": host,
        "DB_USER": user,
        "DB_PASSWORD": password,
    }
    return subprocess.run(
        ["alembic", *args],
        capture_output=True,
        text=True,
        cwd="/app",
        env=env,
    )


# ---------------------------------------------------------------------------
# Fixture de banco dedicado
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def test_db():
    """
    Cria rsvp_test limpo antes do módulo; dropa ao terminar.
    Garante banco 100% vazio sem init.sql.
    """
    if not _mysql_available():
        pytest.skip("MySQL não disponível — rode dentro do container Docker")

    admin = _admin_engine()
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB}"))
        conn.execute(
            text(
                f"CREATE DATABASE {TEST_DB} "
                "DEFAULT CHARACTER SET utf8mb4 "
                "COLLATE utf8mb4_unicode_ci"
            )
        )

    engine = _test_engine()
    yield engine

    engine.dispose()
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB}"))
    admin.dispose()


# ---------------------------------------------------------------------------
# Testes — executados em ordem de arquivo dentro da classe
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestMigration0001:
    """
    Ciclo completo: banco vazio → upgrade head → validações → downgrade base
    → validações → re-upgrade. Os testes estão numerados e pytest os executa
    na ordem em que aparecem no arquivo.
    """

    def test_01_upgrade_applies_cleanly(self, test_db):
        """alembic upgrade head deve aplicar sem erro num banco vazio."""
        result = _run_alembic("upgrade", "head")
        assert result.returncode == 0, (
            f"upgrade head falhou.\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
        assert "Running upgrade" in result.stderr, (
            "Esperava mensagem 'Running upgrade' — migration pode ter sido ignorada"
        )

    def test_02_all_tables_exist(self, test_db):
        """As 6 tabelas do schema SaaS devem existir após upgrade."""
        expected = {
            "tenants",
            "users",
            "events",
            "invitees",
            "password_reset_tokens",
            "plan_limits",
        }
        with test_db.connect() as conn:
            rows = conn.execute(text("SHOW TABLES")).fetchall()
        tables = {row[0] for row in rows}
        assert expected.issubset(tables), f"Tabelas ausentes: {expected - tables}"

    def test_03_tenant_id_isolation_indexes_exist(self, test_db):
        """Índices de isolamento por tenant_id devem existir em users, events e invitees."""
        expected = {
            ("users", "idx_users_tenant"),
            ("events", "idx_events_tenant"),
            ("invitees", "idx_invitees_tenant"),
        }
        with test_db.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT table_name, index_name
                    FROM information_schema.statistics
                    WHERE table_schema = :db
                      AND index_name IN (
                          'idx_users_tenant',
                          'idx_events_tenant',
                          'idx_invitees_tenant'
                      )
                    GROUP BY table_name, index_name
                """),
                {"db": TEST_DB},
            ).fetchall()
        found = {(row[0], row[1]) for row in rows}
        assert expected == found, f"Índices ausentes: {expected - found}"

    def test_04_both_invitees_fk_cascade_paths(self, test_db):
        """
        invitees deve ter DUAS FKs de cascade até tenants:
          fk_invitees_event  → events  → tenants (via cascade em events)
          fk_invitees_tenant → tenants (direto)

        MySQL/InnoDB aceita ambos os caminhos; SQL Server bloquearia com
        'multiple cascade paths' — essa é a distinção que o schema documenta.
        """
        expected_invitees_fks = {"fk_invitees_event", "fk_invitees_tenant"}
        with test_db.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT constraint_name, referenced_table_name
                    FROM information_schema.referential_constraints
                    WHERE constraint_schema = :db
                      AND table_name = 'invitees'
                """),
                {"db": TEST_DB},
            ).fetchall()
        found_names = {row[0] for row in rows}
        assert expected_invitees_fks == found_names, (
            f"FKs de invitees inesperadas. Esperado: {expected_invitees_fks}, "
            f"encontrado: {found_names}"
        )
        # Confirma que os dois destinos são os esperados
        found_targets = {row[1] for row in rows}
        assert found_targets == {"events", "tenants"}, (
            f"Targets das FKs de invitees incorretos: {found_targets}"
        )

    def test_05_all_foreign_keys_exist(self, test_db):
        """Todas as FKs críticas do schema SaaS devem existir."""
        expected_fks = {
            ("events", "fk_events_owner"),
            ("events", "fk_events_tenant"),
            ("invitees", "fk_invitees_event"),
            ("invitees", "fk_invitees_tenant"),
            ("password_reset_tokens", "fk_prt_user"),
            ("users", "fk_users_tenant"),
        }
        with test_db.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT table_name, constraint_name
                    FROM information_schema.referential_constraints
                    WHERE constraint_schema = :db
                """),
                {"db": TEST_DB},
            ).fetchall()
        found = {(row[0], row[1]) for row in rows}
        missing = expected_fks - found
        assert not missing, f"FKs ausentes: {missing}"

    def test_06_invitees_has_denormalized_tenant_id(self, test_db):
        """invitees.tenant_id deve existir como coluna desnormalizada."""
        with test_db.connect() as conn:
            count = conn.execute(
                text("""
                    SELECT COUNT(*)
                    FROM information_schema.columns
                    WHERE table_schema = :db
                      AND table_name = 'invitees'
                      AND column_name = 'tenant_id'
                """),
                {"db": TEST_DB},
            ).scalar()
        assert count == 1, "invitees.tenant_id não encontrado"

    def test_07_users_email_globally_unique(self, test_db):
        """users.email deve ter UNIQUE KEY global (uq_users_email, non_unique=0)."""
        with test_db.connect() as conn:
            count = conn.execute(
                text("""
                    SELECT COUNT(*)
                    FROM information_schema.statistics
                    WHERE table_schema = :db
                      AND table_name = 'users'
                      AND index_name = 'uq_users_email'
                      AND non_unique = 0
                """),
                {"db": TEST_DB},
            ).scalar()
        assert count >= 1, "UNIQUE KEY uq_users_email não encontrado em users"

    def test_08_downgrade_removes_saas_tables(self, test_db):
        """alembic downgrade base deve remover todas as tabelas do schema SaaS."""
        result = _run_alembic("downgrade", "base")
        assert result.returncode == 0, (
            f"downgrade base falhou.\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
        saas_tables = {
            "tenants", "users", "events", "invitees",
            "password_reset_tokens", "plan_limits",
        }
        with test_db.connect() as conn:
            rows = conn.execute(text("SHOW TABLES")).fetchall()
        remaining = {row[0] for row in rows} & saas_tables
        assert not remaining, f"Tabelas ainda presentes após downgrade: {remaining}"

    def test_09_reupgrade_after_downgrade(self, test_db):
        """Re-aplicar upgrade head após downgrade deve funcionar sem erro."""
        result = _run_alembic("upgrade", "head")
        assert result.returncode == 0, (
            f"re-upgrade falhou.\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
        expected = {
            "tenants", "users", "events", "invitees",
            "password_reset_tokens", "plan_limits",
        }
        with test_db.connect() as conn:
            rows = conn.execute(text("SHOW TABLES")).fetchall()
        tables = {row[0] for row in rows}
        assert expected.issubset(tables), (
            f"Tabelas ausentes após re-upgrade: {expected - tables}"
        )

    def test_10_plan_limits_seed_free(self, test_db):
        """Plano free deve ter max_events=2, max_invitees=50, max_members=1."""
        with test_db.connect() as conn:
            row = conn.execute(text(
                "SELECT max_events, max_invitees, max_members "
                "FROM plan_limits WHERE plan = 'free'"
            )).mappings().fetchone()
        assert row is not None, "Linha 'free' ausente em plan_limits"
        assert row["max_events"]   == 2,  f"max_events free esperado 2, obteve {row['max_events']}"
        assert row["max_invitees"] == 50, f"max_invitees free esperado 50, obteve {row['max_invitees']}"
        assert row["max_members"]  == 1,  f"max_members free esperado 1, obteve {row['max_members']}"

    def test_11_plan_limits_seed_pro(self, test_db):
        """Plano pro deve ter max_events=10, max_invitees=500, max_members=5."""
        with test_db.connect() as conn:
            row = conn.execute(text(
                "SELECT max_events, max_invitees, max_members "
                "FROM plan_limits WHERE plan = 'pro'"
            )).mappings().fetchone()
        assert row is not None, "Linha 'pro' ausente em plan_limits"
        assert row["max_events"]   == 10,  f"max_events pro esperado 10, obteve {row['max_events']}"
        assert row["max_invitees"] == 500, f"max_invitees pro esperado 500, obteve {row['max_invitees']}"
        assert row["max_members"]  == 5,   f"max_members pro esperado 5, obteve {row['max_members']}"

    def test_12_plan_limits_business_is_unlimited(self, test_db):
        """Plano business deve ter todos os limites NULL (ilimitado)."""
        with test_db.connect() as conn:
            row = conn.execute(text(
                "SELECT max_events, max_invitees, max_members "
                "FROM plan_limits WHERE plan = 'business'"
            )).mappings().fetchone()
        assert row is not None, "Linha 'business' ausente em plan_limits"
        assert row["max_events"]   is None, "max_events business deve ser NULL"
        assert row["max_invitees"] is None, "max_invitees business deve ser NULL"
        assert row["max_members"]  is None, "max_members business deve ser NULL"
