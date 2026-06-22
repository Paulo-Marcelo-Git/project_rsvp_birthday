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
    'ADMIN_USER': 'testadmin',
    'ADMIN_EMAIL': 'testadmin@test.com',
    'ADMIN_PASS': generate_password_hash(ADMIN_PASSWORD),
    'DEFAULT_PASSWORD': 'Default@1234',
})

# Patch do engine antes de importar o app (evita tentativa de conexão MySQL)
_mock_engine = MagicMock()
with patch('sqlalchemy.create_engine', return_value=_mock_engine):
    import app as _app_module

flask_app = _app_module.app
flask_app.config.update({'TESTING': True, 'WTF_CSRF_ENABLED': False})


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
    """Client com sessão de super admin pré-configurada (não requer DB)."""
    with client.session_transaction() as sess:
        sess['_user_id'] = 'admin'
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
