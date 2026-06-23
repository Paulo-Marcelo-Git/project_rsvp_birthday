# backend/tests/test_rate_limiting.py
"""5A-1 / 5A-2 — Flask-Limiter: registro, disable em testes, limites por rota."""

import os
import pytest
from tests.conftest import flask_app, setup_db, qresult


# ── 5A-1: registro e configuração ─────────────────────────────────────────────

def test_limiter_is_registered():
    """app.py deve expor o objeto 'limiter' (Flask-Limiter)."""
    import app as app_module
    assert hasattr(app_module, 'limiter'), "app.py deve expor 'limiter'"


def test_limiter_disabled_em_testes(client):
    """conftest.py deve setar limiter.enabled=False para não bloquear testes."""
    import app as app_module
    # Flask-Limiter 3.x fixa self.enabled no init_app(); conftest seta direto no obj.
    assert not app_module.limiter.enabled, (
        "Rate limiting deve estar DESABILITADO em testes (conftest seta limiter.enabled=False)"
    )


def test_limiter_storage_memory_quando_sem_redis(monkeypatch):
    """Sem REDIS_URL no env, o limiter usa storage memory:// como fallback."""
    import app as app_module
    assert app_module.limiter is not None
    # storage_uri foi definido como os.getenv("REDIS_URL", "memory://") em tempo de criação
    assert app_module.limiter._storage_uri in (None, "memory://")


# ── 5A-2: handler 429 ─────────────────────────────────────────────────────────

def test_handler_429_esta_registrado():
    """O app deve ter um errorhandler personalizado para o status 429."""
    import app as app_module
    # Flask armazena handlers em error_handler_spec[blueprint][code][exception]
    spec = app_module.app.error_handler_spec
    handlers_429 = {
        exc: handler
        for bp_handlers in spec.values()
        for code, exc_handlers in bp_handlers.items()
        for exc, handler in exc_handlers.items()
        if code == 429
    }
    assert handlers_429, "Deve existir um errorhandler para 429"


# ── 5A-2: limites por rota — verificação via atributos do Flask-Limiter ──────

def _get_route_limits(app_module):
    """
    Retorna dict de {endpoint_short_name: OrderedSet de LimitGroup} do Flask-Limiter 3.x.
    A API interna usa limit_manager._decorated_limits com chaves 'app.<blueprint>.<func>'.
    Retornamos um dict simplificado {func_name: limits} para facilitar os asserts.
    """
    decorated = app_module.limiter.limit_manager._decorated_limits
    result = {}
    for full_key, limits in decorated.items():
        # chave: 'app.login.login' → 'login'; 'app.forgot_password.forgot_password' → 'forgot_password'
        short = full_key.split('.')[-1]
        result[short] = limits
    return result


def test_login_rate_limit_aplicado():
    """POST /login deve ter rate limit configurado (10/min)."""
    import app as app_module
    limits = _get_route_limits(app_module)
    assert 'login' in limits, "/login deve ter rate limit registrado"
    assert len(limits['login']) > 0


def test_signup_rate_limit_aplicado():
    """POST /signup deve ter rate limit configurado (5/hora)."""
    import app as app_module
    limits = _get_route_limits(app_module)
    assert 'signup' in limits, "/signup deve ter rate limit registrado"
    assert len(limits['signup']) > 0


def test_forgot_password_rate_limit_aplicado():
    """POST /forgot_password deve ter rate limit configurado (5/hora)."""
    import app as app_module
    limits = _get_route_limits(app_module)
    assert 'forgot_password' in limits, "/forgot_password deve ter rate limit registrado"
    assert len(limits['forgot_password']) > 0


def test_invite_get_rate_limit_aplicado():
    """GET /invite/<token> deve ter rate limit configurado (30/min)."""
    import app as app_module
    limits = _get_route_limits(app_module)
    assert 'invite' in limits, "/invite/<token> deve ter rate limit registrado"


def test_invite_post_rate_limit_aplicado():
    """POST /invite/<token> deve ter rate limit configurado (10/min) para RSVP."""
    import app as app_module
    limits = _get_route_limits(app_module)
    # invite tem 2 limites: GET (30/min) + POST (10/min)
    invite_limits = limits.get('invite', [])
    assert len(invite_limits) >= 2, (
        "/invite deve ter 2 limites (GET 30/min e POST 10/min), "
        f"mas tem {len(invite_limits)}"
    )
