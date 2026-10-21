import os
import tempfile
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
# O import do app abre o arquivo de log na construção: manda para tmp, não para o repo.
os.environ.setdefault('LOG_FILE', os.path.join(tempfile.mkdtemp(prefix='rsvp-test-logs-'), 'app.log'))

# Patch do engine antes de importar o app (evita tentativa de conexão MySQL)
_mock_engine = MagicMock()
with patch('sqlalchemy.create_engine', return_value=_mock_engine):
    import app as _app_module

flask_app = _app_module.app
flask_app.config.update({
    'TESTING': True,
    'WTF_CSRF_ENABLED': False,
})
# Flask-Limiter 3.x fixa self.enabled no init_app(); setar via config não basta.
_app_module.limiter.enabled = False

# DbUser pré-construído para admin_client — retornado sem tocar no DB
_ADMIN_DBUSER = _app_module.DbUser(
    1, 'testadmin', generate_password_hash(ADMIN_PASSWORD), False, 1, 'tenant_admin'
)

SUPERADMIN_EMAIL = 'superadmin@test.com'

_SUPERADMIN_DBUSER = _app_module.DbUser(
    999, 'superadmin', generate_password_hash('Superpass@1'), False, 99, 'super_admin',
    email=SUPERADMIN_EMAIL,
)

# DbUser pré-construído para member_client — role='member', mesmo tenant do
# admin_client (tenant_id=1) mas db_id diferente, pra testar checagem de
# ownership (tenant_admin sempre bypassa, member só acessa o que é seu).
_MEMBER_DBUSER = _app_module.DbUser(
    2, 'membertest', generate_password_hash('MemberPass@1'), False, 1, 'member',
    email='member@test.com',
)


@_app_module.login_manager.user_loader
def _test_user_loader(user_id):
    """Loader de teste: IDs fixos retornam usuários pré-construídos; outros consultam o mock."""
    if user_id == 'user_1':
        return _ADMIN_DBUSER
    if user_id == 'user_999':
        return _SUPERADMIN_DBUSER
    if user_id == 'user_2':
        return _MEMBER_DBUSER
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
def member_client(client):
    """Client com sessão de member (role='member', tenant_id=1, db_id=2) pré-configurada."""
    with client.session_transaction() as sess:
        sess['_user_id'] = 'user_2'
        sess['_fresh'] = True
    return client


@pytest.fixture
def superadmin_client(client):
    """Client autenticado como super-admin (role='super_admin')."""
    with client.session_transaction() as sess:
        sess['_user_id'] = 'user_999'
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
    'title': 'Festa Teste',
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


import datetime as _dt

EVENT_ROW = {
    'id': 1, 'tenant_id': 1, 'owner_user_id': 1, 'title': 'Festa Teste',
    'status': 'draft', 'theme': 'default', 'media_url': 'evento.jpg',
    'event_date': None, 'created_at': _dt.datetime(2026, 1, 1), 'total_invitees': 0,
}

LIMITS_NONE = {'max_events': None, 'max_invitees': None, 'max_members': None}

# Amostras mínimas com a assinatura (magic bytes) correta de cada formato.
JPEG_BYTES = b'\xff\xd8\xff\xe0' + b'\x00' * 32
PNG_BYTES = b'\x89PNG\r\n\x1a\n' + b'\x00' * 32
MP4_BYTES = b'\x00\x00\x00\x18ftypmp42' + b'\x00' * 32


def respostas_db(db, guests=None, limits=None, events=None):
    """Mocka as 5 queries de GET /admin/respostas?event_id=1, na ordem:
    list_events, get_invitees, count_invitees_by_response, get_event_texts, get_plan_limits."""
    return setup_db(
        db,
        qresult(all_rows=events if events is not None else [EVENT_ROW]),
        qresult(all_rows=guests or []),
        qresult(fetchone=STATS_ROW),
        qresult(fetchone=TEXTS_ROW),
        qresult(fetchone=limits or LIMITS_NONE),
    )


@pytest.fixture
def upload_dir(tmp_path, monkeypatch):
    """Aponta UPLOAD_FOLDER para um diretório temporário vazio."""
    monkeypatch.setitem(flask_app.config, 'UPLOAD_FOLDER', str(tmp_path))
    return tmp_path
