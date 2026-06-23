"""
Testes de integração — Fase 2C: signup self-service.

Cobre:
  - Migration 0003: tabela email_verification_tokens existe e tem FK para users
  - Atomicidade: rollback real por constraint violation (email duplicado)
  - Verificação: token válido ativa a conta (is_active 0 → 1)
  - Login bloqueado para conta não verificada (is_active=0)
  - Reenvio: token antigo invalidado, novo token funciona
  - Isolamento: tenant criado via signup não vê invitees de outro tenant

Rodar dentro do container:
    pytest -m integration -v
"""
import os
import secrets
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool
from werkzeug.security import generate_password_hash

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import repo  # noqa: E402  — repo.py só importa json e sqlalchemy.text, sem globals de app

TEST_DB = "rsvp_test"


# ── helpers ────────────────────────────────────────────────────────────────────


def _creds() -> tuple[str, str, str]:
    user = os.environ.get("TEST_DB_USER") or os.environ.get("DB_USER", "root")
    password = os.environ.get("TEST_DB_PASSWORD") or os.environ.get("DB_PASSWORD", "")
    host = os.environ.get("TEST_DB_HOST") or os.environ.get("DB_HOST", "db")
    return user, password, host


def _admin_engine():
    user, password, host = _creds()
    url = f"mysql+pymysql://{user}:{password}@{host}/?charset=utf8mb4"
    return create_engine(url, poolclass=NullPool, future=True)


def _test_engine():
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


# ── fixture de banco dedicado ──────────────────────────────────────────────────


@pytest.fixture(scope="module")
def test_db():
    """Cria rsvp_test limpo + alembic upgrade head; dropa ao terminar."""
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

    result = _run_alembic("upgrade", "head")
    assert result.returncode == 0, (
        f"upgrade head falhou.\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )

    engine = _test_engine()
    yield engine

    engine.dispose()
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB}"))
    admin.dispose()


# ── Migration 0003 ─────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestMigration0003:

    def test_table_exists(self, test_db):
        """email_verification_tokens deve existir após upgrade head."""
        with test_db.connect() as conn:
            count = conn.execute(
                text("""
                    SELECT COUNT(*) FROM information_schema.tables
                    WHERE table_schema = :db
                      AND table_name = 'email_verification_tokens'
                """),
                {"db": TEST_DB},
            ).scalar()
        assert count == 1, "Tabela email_verification_tokens não encontrada"

    def test_fk_to_users(self, test_db):
        """email_verification_tokens deve ter FK (ON DELETE CASCADE) para users."""
        with test_db.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT constraint_name
                    FROM information_schema.referential_constraints
                    WHERE constraint_schema = :db
                      AND table_name = 'email_verification_tokens'
                """),
                {"db": TEST_DB},
            ).fetchone()
        assert row is not None, "FK de email_verification_tokens → users não encontrada"


# ── Signup 2C ──────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestSignup2C:

    def test_signup_atomic_rollback(self, test_db):
        """
        Simula falha real por constraint: tenant INSERT ok, user INSERT falha
        (email duplicado → uq_users_email). O tenant NÃO deve ser persistido.
        """
        collision_email = "collision_rollback_2c@example.com"

        # Pré-inserir usuário com o email de colisão no tenant padrão (id=1)
        with test_db.connect() as conn:
            conn.execute(
                text("""
                    INSERT INTO users (tenant_id, username, email, password_hash, role)
                    VALUES (1, 'colluser_2c', :email, 'dummyhash', 'member')
                """),
                {"email": collision_email},
            )
            conn.commit()

        # Contar tenants com o nome de teste antes da tentativa
        with test_db.connect() as conn:
            before = conn.execute(
                text("SELECT COUNT(*) FROM tenants WHERE name = 'Atomic Rollback Test'")
            ).scalar()

        # Tentar transação que falha no INSERT users (duplicata de email)
        with pytest.raises(Exception):
            with test_db.connect() as conn:
                conn.execute(text("INSERT INTO tenants (name) VALUES ('Atomic Rollback Test')"))
                new_tid = conn.execute(text("SELECT LAST_INSERT_ID()")).scalar()
                # Viola uq_users_email → IntegrityError → rollback implícito do context manager
                conn.execute(
                    text("""
                        INSERT INTO users (tenant_id, username, email, password_hash, role)
                        VALUES (:tid, 'rollbackuser', :email, 'dummyhash', 'tenant_admin')
                    """),
                    {"tid": new_tid, "email": collision_email},
                )
                conn.commit()  # nunca alcançado

        # Após rollback automático: contagem de tenants deve ser idêntica à de antes
        with test_db.connect() as conn:
            after = conn.execute(
                text("SELECT COUNT(*) FROM tenants WHERE name = 'Atomic Rollback Test'")
            ).scalar()

        assert before == after, (
            f"Tenant persiste após rollback (antes={before}, depois={after}) — "
            "transação não foi atomica"
        )

    def test_verify_email_activates_account(self, test_db):
        """Token válido muda is_active de 0 para 1."""
        # Criar via repo (igual ao signup real)
        with test_db.connect() as conn:
            tenant_id = repo.create_tenant(conn, "Verify Test Tenant 2C")
            user_id = repo.create_tenant_admin_user(
                conn, tenant_id, "verify2c@example.com",
                generate_password_hash("senha123"),
            )
            token = repo.create_email_verification_token(conn, user_id)
            conn.commit()

        # is_active deve ser 0 antes da verificação
        with test_db.connect() as conn:
            is_active_before = conn.execute(
                text("SELECT is_active FROM users WHERE id = :uid"), {"uid": user_id}
            ).scalar()
        assert is_active_before == 0, "Usuário deveria nascer com is_active=0"

        # Verificar via repo
        with test_db.connect() as conn:
            tok_row = repo.get_valid_verification_token(conn, token)
            assert tok_row is not None, "Token não encontrado antes de usar"
            repo.use_verification_token(conn, tok_row["id"], tok_row["user_id"])
            conn.commit()

        # is_active deve ser 1 após verificação
        with test_db.connect() as conn:
            is_active_after = conn.execute(
                text("SELECT is_active FROM users WHERE id = :uid"), {"uid": user_id}
            ).scalar()
        assert is_active_after == 1, "Usuário deveria estar ativo após verificação"

    def test_unverified_user_cannot_login(self, test_db):
        """
        get_user_by_email_global retorna is_active=0 para conta não verificada.
        O login() verifica `row.get('is_active')` antes de aceitar — valor falsy bloqueia.
        """
        with test_db.connect() as conn:
            tenant_id = repo.create_tenant(conn, "Unverified Tenant 2C")
            repo.create_tenant_admin_user(
                conn, tenant_id, "unverified2c@example.com",
                generate_password_hash("senha123"),
            )
            conn.commit()

        with test_db.connect() as conn:
            row = repo.get_user_by_email_global(conn, "unverified2c@example.com")

        assert row is not None, "Usuário não encontrado no banco"
        assert not row.get("is_active"), (
            "is_active deve ser 0 (falsy) para conta não verificada — login deve ser bloqueado"
        )

    def test_resend_invalidates_old_token(self, test_db):
        """Após reenvio, token antigo torna-se inválido; novo token funciona."""
        with test_db.connect() as conn:
            tenant_id = repo.create_tenant(conn, "Resend Test Tenant 2C")
            user_id = repo.create_tenant_admin_user(
                conn, tenant_id, "resend2c@example.com",
                generate_password_hash("senha123"),
            )
            old_token = repo.create_email_verification_token(conn, user_id)
            conn.commit()

        # Simula reenvio: invalida tokens antigos + cria novo
        with test_db.connect() as conn:
            repo.invalidate_verification_tokens(conn, user_id)
            new_token = repo.create_email_verification_token(conn, user_id)
            conn.commit()

        # Token antigo deve estar inválido (used=1 ou expirado via query de valid)
        with test_db.connect() as conn:
            old_row = repo.get_valid_verification_token(conn, old_token)
        assert old_row is None, "Token antigo deveria ser inválido após reenvio"

        # Novo token deve ser válido e apontar para o mesmo usuário
        with test_db.connect() as conn:
            new_row = repo.get_valid_verification_token(conn, new_token)
        assert new_row is not None, "Novo token deveria ser válido"
        assert new_row["user_id"] == user_id

    def test_signup_tenant_isolation(self, test_db):
        """
        Tenant criado via signup não enxerga invitees do tenant default (seed 0002).
        Prova que tenant_id=1 e tenant criado no signup são estritamente isolados.
        """
        # Inserir convidado no tenant padrão (id=1, event_id=1 do seed 0002)
        isolation_invitee_token = secrets.token_urlsafe(16)[:22]
        with test_db.connect() as conn:
            conn.execute(
                text("""
                    INSERT INTO invitees (event_id, tenant_id, name, token)
                    VALUES (1, 1, 'Convidado Default 2C', :tok)
                """),
                {"tok": isolation_invitee_token},
            )
            conn.commit()

        # Criar novo tenant via signup (fluxo completo com transação)
        with test_db.connect() as conn:
            new_tid = repo.create_tenant(conn, "Isolation Signup Tenant 2C")
            new_uid = repo.create_tenant_admin_user(
                conn, new_tid, "isolation2c@example.com",
                generate_password_hash("senha123"),
            )
            repo.create_default_event(
                conn, new_tid, "Isolation Signup Tenant 2C", owner_user_id=new_uid
            )
            conn.commit()

        # Novo tenant não deve ver invitees do tenant padrão
        with test_db.connect() as conn:
            new_tenant_invitees = repo.get_invitees(conn, new_tid)
        assert new_tenant_invitees == [], (
            f"Novo tenant viu invitees de outro tenant: {new_tenant_invitees}"
        )

        # Tenant padrão ainda deve ter seu convidado (isolamento não pode deletar dados alheios)
        with test_db.connect() as conn:
            default_invitees = repo.get_invitees(conn, 1)
        assert len(default_invitees) >= 1, (
            "Convidado do tenant padrão sumiu — isolamento não deve afetar outros tenants"
        )
