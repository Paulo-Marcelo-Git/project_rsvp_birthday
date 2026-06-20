from tests.conftest import setup_db, qresult
from unittest.mock import MagicMock, patch


def test_init_db_cria_tabela_tokens(db, monkeypatch):
    """init_db() deve interagir com o engine ao criar/migrar tabelas."""
    import app as _app
    monkeypatch.setattr(_app, 'engine', db)
    conn = MagicMock()
    conn.execute.return_value = MagicMock()
    db.connect.return_value.__enter__.return_value = conn

    _app.init_db()

    assert db.connect.called
    assert conn.execute.called
