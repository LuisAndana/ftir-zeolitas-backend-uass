"""Pruebas de las medidas de ciberseguridad: tipos de token, fuerza bruta, limitador, contrasenas y cabeceras."""

import pytest
from fastapi import HTTPException
from jose import JWTError

from app.core import rate_limit as rl
from app.core.security import (
    TokenManager,
    burn_password_check,
    generate_tokens,
    validate_password_strength,
)


@pytest.fixture(autouse=True)
def _limpiar_limitador():
    rl.limiter.clear()
    yield
    rl.limiter.clear()


# ---------------- Tokens: access y refresh no son intercambiables ----------------

def test_refresh_token_no_sirve_como_access():
    t = generate_tokens(1)
    with pytest.raises(JWTError):
        TokenManager.verify_token(t["refresh_token"], expected_type="access")


def test_access_token_no_sirve_para_renovar():
    t = generate_tokens(1)
    with pytest.raises(JWTError):
        TokenManager.verify_token(t["access_token"], expected_type="refresh")


def test_tokens_validos_con_su_tipo():
    t = generate_tokens(7)
    assert TokenManager.verify_token(t["access_token"], expected_type="access")["sub"] == "7"
    assert TokenManager.verify_token(t["refresh_token"], expected_type="refresh")["sub"] == "7"


def test_token_antiguo_sin_tipo_se_rechaza():
    antiguo = TokenManager.create_access_token({"sub": 1})
    import jwt as pyjwt
    from app.core.config import settings
    payload = pyjwt.decode(antiguo, settings.secret_key, algorithms=[settings.algorithm])
    payload.pop("type")
    sin_tipo = pyjwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)
    with pytest.raises(JWTError):
        TokenManager.verify_token(sin_tipo, expected_type="access")


# ---------------- Contrasenas ----------------

@pytest.mark.parametrize("malas", ["corta1", "soloLetrasAqui", "123456789012", "password123", "x" * 129 + "1"])
def test_contrasenas_debiles_se_rechazan(malas):
    assert validate_password_strength(malas) is not None


def test_contrasena_aceptable():
    assert validate_password_strength("Zeolita-Y-2026x") is None


def test_burn_password_check_no_falla():
    burn_password_check("cualquier cosa")


# ---------------- Bloqueo de login ----------------

def test_login_se_bloquea_tras_5_fallos_de_la_misma_cuenta_e_ip():
    for _ in range(5):
        assert rl.login_blocked_for("a@x.com", "1.1.1.1") == 0
        rl.login_failed("a@x.com", "1.1.1.1")
    assert rl.login_blocked_for("a@x.com", "1.1.1.1") > 0


def test_bloqueo_no_afecta_a_la_cuenta_desde_otra_ip():
    for _ in range(5):
        rl.login_failed("victima@x.com", "6.6.6.6")
    assert rl.login_blocked_for("victima@x.com", "6.6.6.6") > 0
    assert rl.login_blocked_for("victima@x.com", "9.9.9.9") == 0   # el usuario legitimo sigue entrando


def test_una_ip_probando_muchas_cuentas_se_bloquea():
    for i in range(20):
        rl.login_failed(f"u{i}@x.com", "2.2.2.2")
    assert rl.login_blocked_for("otra@x.com", "2.2.2.2") > 0


def test_login_exitoso_reinicia_el_contador():
    for _ in range(4):
        rl.login_failed("a@x.com", "1.1.1.1")
    rl.login_succeeded("a@x.com", "1.1.1.1")
    assert rl.login_blocked_for("a@x.com", "1.1.1.1") == 0


# ---------------- Limitador generico ----------------

class _Req:
    def __init__(self, host="8.8.8.8", real=None):
        self.client = type("C", (), {"host": host})()
        self.headers = {"x-real-ip": real} if real else {}


def test_rate_limit_devuelve_429_con_retry_after():
    dep = rl.rate_limit("t", 3, 60)
    for _ in range(3):
        dep(_Req())
    with pytest.raises(HTTPException) as exc:
        dep(_Req())
    assert exc.value.status_code == 429
    assert int(exc.value.headers["Retry-After"]) >= 1


def test_rate_limit_es_por_ip():
    dep = rl.rate_limit("t", 1, 60)
    dep(_Req(host="8.8.8.8"))
    dep(_Req(host="8.8.4.4"))   # otra IP: no se limita


def test_x_real_ip_solo_se_confia_desde_red_privada():
    # Desde Internet no se puede falsificar la IP con la cabecera
    assert rl.client_ip(_Req(host="8.8.8.8", real="1.2.3.4")) == "8.8.8.8"
    # Desde nginx (red privada de Docker) si se usa la IP real que el reenvia
    assert rl.client_ip(_Req(host="172.18.0.5", real="1.2.3.4")) == "1.2.3.4"
    # Un valor que no es IP se ignora
    assert rl.client_ip(_Req(host="172.18.0.5", real="<script>")) == "172.18.0.5"


# ---------------- Cabeceras y documentacion ----------------

def test_api_responde_con_cabeceras_de_seguridad():
    import asyncio
    from starlette.responses import JSONResponse
    from main import security_headers

    class _Url:
        path = "/api/zeolites"

    class _Request:
        url = _Url()

    async def call_next(_):
        return JSONResponse({"ok": True})

    r = asyncio.run(security_headers(_Request(), call_next))
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store"
