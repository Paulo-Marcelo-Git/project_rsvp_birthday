"""
Testes unitários de repo.py — verificam que tenant_id aparece sempre nos
parâmetros das queries e que as funções globais NÃO filtram por tenant.

Usam mocks leves de conn.execute; não precisam de banco real.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
import repo


# ── helper de mock ────────────────────────────────────────────────────────────

def _conn(fetchone=None, all_rows=None, rowcount=1):
    conn = MagicMock()
    result = MagicMock()
    mapped = MagicMock()
    mapped.fetchone.return_value = fetchone
    mapped.all.return_value = all_rows or []
    result.mappings.return_value = mapped
    result.rowcount = rowcount
    conn.execute.return_value = result
    return conn


def _last_params(conn):
    """Retorna os parâmetros da última chamada a conn.execute."""
    return conn.execute.call_args[0][1]


def _all_sqls(conn):
    """Retorna todos os textos SQL executados."""
    return [str(call[0][0]) for call in conn.execute.call_args_list]


# ── invitees ──────────────────────────────────────────────────────────────────

def test_get_invitees_filtra_tenant_id():
    c = _conn(all_rows=[])
    repo.get_invitees(c, tenant_id=42)
    assert _last_params(c)["tid"] == 42


def test_get_invitees_com_owner_inclui_owner_no_filtro():
    c = _conn(all_rows=[])
    repo.get_invitees(c, 42, owner_user_id=7)
    sql = str(c.execute.call_args[0][0])
    assert "owner_user_id" in sql


def test_get_invitees_com_search_inclui_like():
    c = _conn(all_rows=[])
    repo.get_invitees(c, 42, search="Ana")
    params = _last_params(c)
    assert params["tid"] == 42
    assert "Ana" in params["search"]


def test_get_invitees_sem_owner_sem_search_sem_extra_where():
    c = _conn(all_rows=[])
    repo.get_invitees(c, 42)
    params = _last_params(c)
    # owner_user_id e search não devem aparecer nos parâmetros (não no SQL base)
    assert "owner_user_id" not in params
    assert "search" not in params


def test_count_invitees_filtra_tenant_id():
    c = _conn(fetchone={"total": 0, "total_sim": 0, "total_nao": 0, "total_aguardando": 0})
    repo.count_invitees_by_response(c, 42)
    assert _last_params(c)["tid"] == 42


def test_add_invitee_grava_tenant_id_e_event_id():
    c = _conn()
    repo.add_invitee(c, 42, 1, "João", "T" * 22)
    params = _last_params(c)
    assert params["tid"] == 42
    assert params["eid"] == 1


def test_get_invitee_filtra_tenant_id():
    c = _conn(fetchone=None)
    repo.get_invitee(c, 42, 99)
    params = _last_params(c)
    assert params["tid"] == 42
    assert params["iid"] == 99


def test_update_invitee_filtra_tenant_id():
    c = _conn(rowcount=1)
    repo.update_invitee(c, 42, 99, name="Novo")
    params = _last_params(c)
    assert params["tid"] == 42
    assert params["iid"] == 99


def test_update_invitee_ignora_campos_nao_permitidos():
    # Passa campo não permitido; deve ser ignorado (não aparecer no SET)
    c = _conn(rowcount=1)
    repo.update_invitee(c, 42, 99, name="OK", event_id=999)
    sql = str(c.execute.call_args[0][0])
    set_clause = sql.split("SET")[1].split("WHERE")[0]
    assert "event_id" not in set_clause
    assert "name" in set_clause


def test_delete_invitee_filtra_tenant_id():
    c = _conn(rowcount=1)
    repo.delete_invitee(c, 42, 99)
    params = _last_params(c)
    assert params["tid"] == 42
    assert params["iid"] == 99


# ── events ────────────────────────────────────────────────────────────────────

def test_get_default_event_id_filtra_tenant_id():
    c = _conn(fetchone={"id": 1})
    repo.get_default_event_id(c, 42)
    assert _last_params(c)["tid"] == 42


def test_get_event_texts_filtra_tenant_id():
    c = _conn(fetchone={
        "title": "Festa", "question_text": "Vai?", "yes_text": "Sim",
        "no_text": "Não", "extra_texts": None,
    })
    repo.get_event_texts(c, 42, 1)
    params = _last_params(c)
    assert params["tid"] == 42
    assert params["eid"] == 1


# ── plan_limits ───────────────────────────────────────────────────────────────

def test_get_plan_limits_filtra_tenant_id():
    c = _conn(fetchone={"max_events": 2, "max_invitees": 50, "max_members": 1})
    repo.get_plan_limits(c, 99)
    assert _last_params(c)["tid"] == 99


def test_get_plan_limits_retorna_valores_corretos():
    c = _conn(fetchone={"max_events": 2, "max_invitees": 50, "max_members": 1})
    limits = repo.get_plan_limits(c, 1)
    assert limits["max_events"] == 2
    assert limits["max_invitees"] == 50
    assert limits["max_members"] == 1


def test_get_plan_limits_retorna_none_para_ilimitado():
    c = _conn(fetchone={"max_events": None, "max_invitees": None, "max_members": None})
    limits = repo.get_plan_limits(c, 1)
    assert limits["max_events"] is None
    assert limits["max_invitees"] is None
    assert limits["max_members"] is None


def test_get_plan_limits_tenant_inexistente_retorna_nulls():
    c = _conn(fetchone=None)
    limits = repo.get_plan_limits(c, 9999)
    assert limits == {"max_events": None, "max_invitees": None, "max_members": None}


def test_within_limit_abaixo_do_limite():
    assert repo.within_limit(0, 1) is True
    assert repo.within_limit(49, 50) is True


def test_within_limit_no_limite():
    assert repo.within_limit(1, 1) is False
    assert repo.within_limit(50, 50) is False


def test_within_limit_ilimitado():
    assert repo.within_limit(0, None) is True
    assert repo.within_limit(9999, None) is True


def test_count_invitees_for_event_filtra_tenant_e_event():
    c = _conn(fetchone={"n": 7})
    result = repo.count_invitees_for_event(c, tenant_id=42, event_id=5)
    params = _last_params(c)
    assert params["tid"] == 42
    assert params["eid"] == 5
    assert result == 7


def test_count_members_for_tenant_filtra_tenant():
    c = _conn(fetchone={"n": 3})
    result = repo.count_members_for_tenant(c, 77)
    assert _last_params(c)["tid"] == 77
    assert result == 3


def test_count_events_for_tenant_filtra_tenant():
    c = _conn(fetchone={"n": 2})
    result = repo.count_events_for_tenant(c, 55)
    assert _last_params(c)["tid"] == 55
    assert result == 2


def test_get_event_texts_extrai_post_texts_do_json():
    c = _conn(fetchone={
        "title": "Festa", "question_text": "Vai?", "yes_text": "Sim", "no_text": "Não",
        "extra_texts": '{"post_yes_text": "Sim!", "post_no_text": "Não!"}',
    })
    result = repo.get_event_texts(c, 1, 1)
    assert result["post_yes_text"] == "Sim!"
    assert result["post_no_text"] == "Não!"


def test_update_event_texts_filtra_tenant_id_em_ambas_queries():
    c = _conn(fetchone={"extra_texts": None})
    repo.update_event_texts(c, 42, 1, question_text="Nova?")
    calls = c.execute.call_args_list
    assert len(calls) == 2
    assert calls[0][0][1]["tid"] == 42  # SELECT
    assert calls[1][0][1]["tid"] == 42  # UPDATE


# ── users ─────────────────────────────────────────────────────────────────────

def test_get_users_filtra_tenant_id():
    c = _conn(all_rows=[])
    repo.get_users(c, 42)
    assert _last_params(c)["tid"] == 42


def test_get_user_by_id_filtra_tenant_id():
    c = _conn(fetchone=None)
    repo.get_user_by_id(c, 42, 7)
    params = _last_params(c)
    assert params["tid"] == 42
    assert params["uid"] == 7


def test_get_user_by_username_filtra_tenant_id():
    c = _conn(fetchone=None)
    repo.get_user_by_username(c, 42, "joao")
    params = _last_params(c)
    assert params["tid"] == 42
    assert params["u"] == "joao"


def test_get_user_by_email_global_nao_filtra_tenant():
    """Email é global — WHERE não deve conter tenant_id."""
    c = _conn(fetchone=None)
    repo.get_user_by_email_global(c, "a@b.com")
    sql = str(c.execute.call_args[0][0])
    where_clause = sql.split("WHERE")[1] if "WHERE" in sql else sql
    assert "tenant_id" not in where_clause


def test_add_user_grava_tenant_id():
    c = _conn(fetchone={"id": 5})
    repo.add_user(c, 42, "maria", "m@t.com", "hash")
    params = c.execute.call_args_list[0][0][1]
    assert params["tid"] == 42


def test_update_user_filtra_tenant_id():
    c = _conn(rowcount=1)
    repo.update_user(c, 42, 7, username="novo")
    params = _last_params(c)
    assert params["tid"] == 42
    assert params["uid"] == 7


def test_update_user_ignora_campos_nao_permitidos():
    # Passa campo não permitido; deve ser ignorado (não aparecer no SET)
    c = _conn(rowcount=1)
    repo.update_user(c, 42, 7, username="ok", table_name="inject")
    sql = str(c.execute.call_args[0][0])
    set_clause = sql.split("SET")[1].split("WHERE")[0]
    assert "table_name" not in set_clause
    assert "username" in set_clause


def test_delete_user_filtra_tenant_id():
    c = _conn(rowcount=1)
    repo.delete_user(c, 42, 7)
    params = _last_params(c)
    assert params["tid"] == 42
    assert params["uid"] == 7


def test_count_invitees_for_user_filtra_tenant_id():
    c = _conn(fetchone={"total": 3})
    repo.count_invitees_for_user(c, 42, 7)
    params = _last_params(c)
    assert params["tid"] == 42
    assert params["uid"] == 7


# ── create_tenant e get_invitee_by_token (sem tenant_id) ─────────────────────

def test_create_tenant_retorna_id():
    c = _conn(fetchone={"id": 10})
    result = repo.create_tenant(c, "Festa da Ana")
    assert result == 10
    # primeiro execute: INSERT; segundo: SELECT LAST_INSERT_ID()
    assert c.execute.call_count == 2


def test_get_invitee_by_token_nao_filtra_tenant():
    """Token é globalmente único — WHERE não deve conter tenant_id."""
    c = _conn(fetchone=None)
    repo.get_invitee_by_token(c, "T" * 22)
    sql = str(c.execute.call_args[0][0])
    where_clause = sql.split("WHERE")[1] if "WHERE" in sql else sql
    assert "tenant_id" not in where_clause


# ── aliases de compatibilidade ────────────────────────────────────────────────

def test_get_invitees_retorna_alias_custom_message():
    """get_invitees deve retornar 'custom_message' como alias de observation."""
    sql = None
    c = _conn(all_rows=[])
    repo.get_invitees(c, 1)
    sql = str(c.execute.call_args[0][0])
    assert "observation" in sql and "custom_message" in sql


def test_get_invitees_retorna_alias_response_date():
    """get_invitees deve retornar 'response_date' como alias de responded_at."""
    c = _conn(all_rows=[])
    repo.get_invitees(c, 1)
    sql = str(c.execute.call_args[0][0])
    assert "responded_at" in sql and "response_date" in sql


# ── system tenant (super-admin only) ──────────────────────────────────────────

def test_get_system_tenant_id_retorna_id_do_tenant_reservado():
    c = _conn(fetchone={'id': 7})
    result = repo.get_system_tenant_id(c)
    assert result == 7
    params = _last_params(c)
    assert params["name"] == repo.SYSTEM_TENANT_NAME


def test_get_system_tenant_id_levanta_erro_se_nao_existir():
    c = _conn(fetchone=None)
    with pytest.raises(RuntimeError):
        repo.get_system_tenant_id(c)


def test_list_all_tenants_exclui_tenant_reservado_na_query():
    c = _conn(all_rows=[])
    repo.list_all_tenants(c)
    sql = str(c.execute.call_args[0][0])
    assert "super_admin" in sql
    assert "NOT EXISTS" in sql


def test_list_all_tenants_seleciona_trial_ends_at():
    c = _conn(all_rows=[])
    repo.list_all_tenants(c)
    sql = str(c.execute.call_args[0][0])
    assert "trial_ends_at" in sql


def test_list_all_tenants_seleciona_suspended_reason():
    c = _conn(all_rows=[])
    repo.list_all_tenants(c)
    sql = str(c.execute.call_args[0][0])
    assert "suspended_reason" in sql


def test_list_all_tenants_seleciona_email_do_tenant_admin():
    c = _conn(all_rows=[])
    repo.list_all_tenants(c)
    sql = str(c.execute.call_args[0][0])
    assert "admin_email" in sql
    assert "tenant_admin" in sql


# ── expiração de trial ────────────────────────────────────────────────────────

def test_get_tenant_status_and_trial_retorna_dict_com_status_plano_e_trial():
    c = _conn(fetchone={
        'status': 'trial', 'plan': 'free', 'trial_ends_at': None,
        'trial_expired': False, 'trial_days_remaining': None,
        'suspended_reason': None,
    })
    result = repo.get_tenant_status_and_trial(c, 5)
    assert result == {
        'status': 'trial', 'plan': 'free', 'trial_ends_at': None,
        'trial_expired': False, 'trial_days_remaining': None,
        'suspended_reason': None,
    }
    params = _last_params(c)
    assert params["tid"] == 5


def test_get_tenant_status_and_trial_seleciona_suspended_reason_no_sql():
    c = _conn(fetchone={'status': 'trial', 'plan': 'free', 'trial_ends_at': None,
                         'trial_expired': False, 'trial_days_remaining': None, 'suspended_reason': None})
    repo.get_tenant_status_and_trial(c, 5)
    sql = str(c.execute.call_args[0][0])
    assert "suspended_reason" in sql


def test_get_tenant_status_and_trial_seleciona_plan_no_sql():
    c = _conn(fetchone={'status': 'trial', 'plan': 'free', 'trial_ends_at': None, 'trial_expired': False, 'trial_days_remaining': None})
    repo.get_tenant_status_and_trial(c, 5)
    sql = str(c.execute.call_args[0][0])
    assert "plan" in sql


def test_get_tenant_status_and_trial_seleciona_dias_restantes_no_sql():
    c = _conn(fetchone={'status': 'trial', 'plan': 'free', 'trial_ends_at': None, 'trial_expired': False, 'trial_days_remaining': None})
    repo.get_tenant_status_and_trial(c, 5)
    sql = str(c.execute.call_args[0][0])
    assert "trial_days_remaining" in sql
    assert "TIMESTAMPDIFF" in sql


def test_get_tenant_status_and_trial_retorna_none_se_tenant_nao_existir():
    c = _conn(fetchone=None)
    result = repo.get_tenant_status_and_trial(c, 999)
    assert result is None


def test_get_tenant_status_and_trial_calcula_expiracao_no_sql():
    """trial_expired deve ser calculado no SQL (UTC_TIMESTAMP), não comparado
    em Python — evita bug de datetime naive vs aware."""
    c = _conn(fetchone={'status': 'trial', 'plan': 'free', 'trial_ends_at': None, 'trial_expired': False, 'trial_days_remaining': None})
    repo.get_tenant_status_and_trial(c, 5)
    sql = str(c.execute.call_args[0][0])
    assert "UTC_TIMESTAMP()" in sql
    assert "trial_expired" in sql


def test_start_tenant_trial_update_e_atomico_com_guarda_trial_ends_at_null():
    """UPDATE guardado por 'AND trial_ends_at IS NULL' — evita que duas
    requisições concorrentes no primeiro login sobrescrevam uma à outra
    (a segunda UPDATE não afeta nenhuma linha, é um no-op seguro)."""
    c = _conn(fetchone={'trial_ends_at': datetime(2026, 1, 1)})
    repo.start_tenant_trial(c, 5)
    first_sql = str(c.execute.call_args_list[0][0][0])
    first_params = c.execute.call_args_list[0][0][1]
    assert "trial_ends_at IS NULL" in first_sql
    assert "INTERVAL" in first_sql
    assert first_params["tid"] == 5
    assert first_params["days"] == repo.TRIAL_DAYS
    assert repo.TRIAL_DAYS == 14


def test_start_tenant_trial_retorna_o_valor_final_persistido():
    """Sempre lê de volta o valor final (SELECT após o UPDATE) — garante que,
    mesmo sob concorrência, a requisição que 'perdeu' a corrida (UPDATE
    no-op) ainda exibe a mesma data que foi realmente persistida."""
    fixed = datetime(2026, 9, 5, 12, 0, 0)
    c = _conn(fetchone={'trial_ends_at': fixed})
    result = repo.start_tenant_trial(c, 5)

    assert result == fixed
    assert c.execute.call_count == 2
    second_sql = str(c.execute.call_args_list[1][0][0])
    second_params = c.execute.call_args_list[1][0][1]
    assert "SELECT" in second_sql
    assert second_params["tid"] == 5


# ── suspended_reason — distingue suspensão por trial de suspensão manual ─────

def test_set_tenant_status_suspended_grava_reason():
    c = _conn()
    repo.set_tenant_status(c, 5, "suspended", reason="trial_expired")
    params = _last_params(c)
    assert params["status"] == "suspended"
    assert params["reason"] == "trial_expired"
    assert params["tid"] == 5


def test_set_tenant_status_manual_grava_reason_manual():
    c = _conn()
    repo.set_tenant_status(c, 5, "suspended", reason="manual")
    params = _last_params(c)
    assert params["reason"] == "manual"


def test_set_tenant_status_nao_suspended_limpa_reason_mesmo_se_passado():
    """Transicionar pra qualquer status != 'suspended' sempre limpa o motivo —
    evita um suspended_reason velho sobrar associado a uma conta já reativada."""
    c = _conn()
    repo.set_tenant_status(c, 5, "active", reason="trial_expired")
    params = _last_params(c)
    assert params["status"] == "active"
    assert params["reason"] is None


# ── password reset tokens ──────────────────────────────────────────────────────

def test_create_password_reset_token_insere_e_retorna_token():
    c = _conn()
    token = repo.create_password_reset_token(c, 42)
    assert isinstance(token, str) and len(token) == 32
    params = _last_params(c)
    assert params["uid"] == 42
    assert params["tok"] == token
    assert isinstance(params["exp"], datetime)
    c.commit.assert_not_called()


def test_create_password_reset_token_default_ttl_1_hora():
    c = _conn()
    before = datetime.now(timezone.utc).replace(tzinfo=None)
    repo.create_password_reset_token(c, 1)
    params = _last_params(c)
    delta = params["exp"] - before
    assert timedelta(hours=1) <= delta < timedelta(hours=1, minutes=1)


def test_create_password_reset_token_aceita_ttl_customizado():
    c = _conn()
    before = datetime.now(timezone.utc).replace(tzinfo=None)
    repo.create_password_reset_token(c, 1, hours=24)
    params = _last_params(c)
    delta = params["exp"] - before
    assert timedelta(hours=24) <= delta < timedelta(hours=24, minutes=1)
