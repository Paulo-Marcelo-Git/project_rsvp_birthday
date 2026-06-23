import os
import pytest
from unittest.mock import MagicMock, patch
from werkzeug.security import generate_password_hash

# Credenciais de teste — devem ser definidas ANTES de importar o app
ADMIN_PASSWORD = 'TestAdmin@99'

os.environ.update({
    'DB_USER': 'test',
    'DB_PASSWORD': 'test',
    'DB_HOST': 'localhost',
    'DB_NAME': 'test_db',
    'SECRET_KEY': 'test-secret-key-for-pytest-only!!',
})

# Patch do engine antes de importar o app (evita tentativa de conexão MySQL)
_mock_engine = MagicMock()
with patch('sqlalchemy.create_engine', return_value=_mock_engine):
    import app as _app_module

flask_app = _app_module.app
flask_app.config.update({'TESTING': True, 'WTF_CSRF_ENABLED': False})

# DbUser pré-construído para admin_client — retornado sem tocar no DB
_ADMIN_DBUSER = _app_module.DbUser(
    1, 'testadmin', generate_password_hash(ADMIN_PASSWORD), False, 1, 'tenant_admin'
)

SUPERADMIN_EMAIL = 'superadmin@test.com'

_SUPERADMIN_DBUSER = _app_module.DbUser(
    999, 'superadmin', generate_password_hash('Superpass@1'), False, 99, 'member',
    email=SUPERADMIN_EMAIL,
)

_MISCONFIG_DBUSER = _app_module.DbUser(
    998, 'misconfigadmin', generate_password_hash('Superpass@1'), False, 1, 'tenant_admin',
    email=SUPERADMIN_EMAIL,
)


@_app_module.login_manager.user_loader
def _test_user_loader(user_id):
    """Loader de teste: IDs fixos retornam usuários pré-construídos; outros consultam o mock."""
    if user_id == 'user_1':
        return _ADMIN_DBUSER
    if user_id == 'user_999':
        return _SUPERADMIN_DBUSER
    if user_id == 'user_998':
        return _MISCONFIG_DBUSER
    if user_id and user_id.startswith('user_'):
        try:
            db_id = int(user_id[5:])
        except ValueError:
            return None
        with _app_module.engine.connect() as conn:
            row = (
                conn.execute(
                    _app_module.text(
                        "SELECT id, tenant_id, username, password_hash, "
                        "must_change_password, role "
                        "FROM users WHERE id=:id AND is_active=1"
                    ),
                    {"id": db_id},
                )
                .mappings()
                .fetchone()
            )
            if row:
                return _app_module.DbUser(
                    row["id"], row["username"], row["password_hash"],
                    row["must_change_password"], row["tenant_id"], row["role"],
                )
    return None


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    with flask_app.test_client() as c:
        yield c


@pytest.fixture
def db(monkeypatch):
    """Engine mock fresco por teste — substitui app.engine."""
    mock = MagicMock()
    monkeypatch.setattr(_app_module, 'engine', mock)
    return mock


@pytest.fixture
def admin_client(client):
    """Client com sessão de tenant_admin pré-configurada (não requer DB)."""
    with client.session_transaction() as sess:
        sess['_user_id'] = 'user_1'
        sess['_fresh'] = True
    return client


@pytest.fixture
def superadmin_client(client, monkeypatch):
    """Client autenticado como superadmin (member, email == SUPERADMIN_EMAIL)."""
    monkeypatch.setenv('SUPERADMIN_EMAIL', SUPERADMIN_EMAIL)
    with client.session_transaction() as sess:
        sess['_user_id'] = 'user_999'
        sess['_fresh'] = True
    return client


@pytest.fixture
def misconfig_client(client, monkeypatch):
    """Client onde SUPERADMIN_EMAIL coincide com um tenant_admin (config inválida)."""
    monkeypatch.setenv('SUPERADMIN_EMAIL', SUPERADMIN_EMAIL)
    with client.session_transaction() as sess:
        sess['_user_id'] = 'user_998'
        sess['_fresh'] = True
    return client


# ── helpers ───────────────────────────────────────────────────────────────────

def qresult(fetchone=None, all_rows=None, rowcount=1):
    """Cria um mock para o retorno de conn.execute()."""
    result = MagicMock()
    result.rowcount = rowcount
    m = MagicMock()
    m.fetchone.return_value = fetchone
    m.all.return_value = all_rows if all_rows is not None else []
    result.mappings.return_value = m
    return result


def setup_db(db_mock, *query_results):
    """
    Configura db_mock.connect() para retornar resultados em sequência.
    Todos os blocos `with engine.connect()` compartilham o mesmo conn mock,
    então os side_effects são consumidos em ordem de chamada ao longo do request.
    """
    conn = MagicMock()
    conn.execute.side_effect = list(query_results)
    db_mock.connect.return_value.__enter__.return_value = conn
    return conn


# ── dados de teste reutilizáveis ──────────────────────────────────────────────

STATS_ROW = {'total': 0, 'total_sim': 0, 'total_nao': 0, 'total_aguardando': 0}

DEFAULT_EVENT_ROW = {'id': 1}

TEXTS_ROW = {
    'question_text': 'Você vai comparecer?',
    'yes_text': 'Sim',
    'no_text': 'Não',
    'extra_texts': '{"post_yes_text": "Obrigado!", "post_no_text": "Sentiremos sua falta!"}',
}

GUEST_ROW = {
    'id': 1,
    'name': 'Maria Silva',
    'email': 'maria@email.com',
    'phone': None,
    'token': 'abc123token',
    'response': 'pending',
    'response_date': None,
    'custom_message': None,
    'media_url': None,
    'owner_username': '(admin)',
    'tenant_id': 1,
    'event_id': 1,
    'event_owner_user_id': None,
}

USER_ROW_FULL = {
    'id': 1,
    'username': 'operador',
    'password_hash': generate_password_hash('Default@1234'),
    'must_change_password': False,
    'email': 'operador@test.com',
    'whatsapp': '11999990000',
    'created_at': None,
    'tenant_id': 1,
    'role': 'member',
    'is_active': 1,
}
