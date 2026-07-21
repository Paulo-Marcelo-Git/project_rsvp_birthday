from tests.conftest import setup_db, qresult, flask_app


def test_create_superadmin_sem_env_var_mostra_erro(monkeypatch):
    monkeypatch.delenv('SUPERADMIN_EMAIL', raising=False)
    runner = flask_app.test_cli_runner()
    result = runner.invoke(args=['create-superadmin'])
    assert 'SUPERADMIN_EMAIL' in result.output


def test_create_superadmin_ja_existe_nao_duplica(db, monkeypatch):
    monkeypatch.setenv('SUPERADMIN_EMAIL', 'sa@test.com')
    setup_db(db, qresult(fetchone={
        'id': 999, 'tenant_id': 5, 'username': 'superadmin', 'email': 'sa@test.com',
        'password_hash': 'x', 'role': 'super_admin', 'must_change_password': False,
        'is_active': 1, 'whatsapp': None,
    }))

    runner = flask_app.test_cli_runner()
    result = runner.invoke(args=['create-superadmin'])

    assert 'Já existe' in result.output


def test_create_superadmin_email_ja_usado_por_conta_comum(db, monkeypatch):
    monkeypatch.setenv('SUPERADMIN_EMAIL', 'sa@test.com')
    setup_db(db, qresult(fetchone={
        'id': 5, 'tenant_id': 1, 'username': 'joao', 'email': 'sa@test.com',
        'password_hash': 'x', 'role': 'tenant_admin', 'must_change_password': False,
        'is_active': 1, 'whatsapp': None,
    }))

    runner = flask_app.test_cli_runner()
    result = runner.invoke(args=['create-superadmin'])

    assert 'já existe como usuário comum' in result.output


def test_create_superadmin_cria_com_sucesso_sem_smtp(db, monkeypatch):
    monkeypatch.setenv('SUPERADMIN_EMAIL', 'sa@test.com')
    monkeypatch.delenv('EMAIL_SMTP', raising=False)
    monkeypatch.delenv('EMAIL_USER', raising=False)
    conn = setup_db(db,
                    qresult(fetchone=None),                  # get_user_by_email_global
                    qresult(fetchone={'id': 7}),               # get_system_tenant_id
                    qresult(),                                 # add_user INSERT
                    qresult(fetchone={'id': 999}))              # LAST_INSERT_ID

    runner = flask_app.test_cli_runner()
    result = runner.invoke(args=['create-superadmin'])

    assert 'Senha temporária' in result.output
    conn.commit.assert_called()
