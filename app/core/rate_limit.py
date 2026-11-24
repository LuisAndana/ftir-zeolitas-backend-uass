"""
Limitador de peticiones en memoria (ventana deslizante) contra fuerza bruta, abuso de correos y sabotaje.

Una sola instancia de uvicorn atiende la API, por eso basta memoria del proceso. Si algun dia se escala a
varios workers/replicas, mover los contadores a Redis (la interfaz publica no cambiaria).
"""

import ipaddress
import threading
import time
from collections import defaultdict, deque
from typing import Callable, Deque, Dict

from fastapi import HTTPException, Request, status


class SlidingWindowLimiter:
    """Cuenta eventos por clave dentro de una ventana de tiempo."""

    def __init__(self) -> None:
        self._events: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _purge(self, key: str, window: float, now: float) -> Deque[float]:
        q = self._events[key]
        while q and now - q[0] > window:
            q.popleft()
        if not q:
            self._events.pop(key, None)
            return deque()
        return q

    def count(self, key: str, window: float) -> int:
        with self._lock:
            return len(self._purge(key, window, time.monotonic()))

    def retry_after(self, key: str, window: float) -> int:
        with self._lock:
            now = time.monotonic()
            q = self._purge(key, window, now)
            return max(1, int(window - (now - q[0])) + 1) if q else 1

    def hit(self, key: str, window: float) -> int:
        with self._lock:
            now = time.monotonic()
            q = self._purge(key, window, now)
            if not q:
                q = self._events[key]
            q.append(now)
            return len(q)

    def reset(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


limiter = SlidingWindowLimiter()


def client_ip(request: Request) -> str:
    """
    IP real del cliente. Detras de nginx/Caddy la conexion llega desde una IP privada de Docker; solo en ese
    caso se confia en X-Real-IP (lo fija nginx con la IP ya resuelta). Una conexion directa desde Internet
    no puede falsificar su IP con esa cabecera.
    """
    peer = request.client.host if request.client else "desconocida"
    try:
        if ipaddress.ip_address(peer).is_private:
            real = request.headers.get("x-real-ip", "").strip()
            if real:
                ipaddress.ip_address(real)  # descarta valores que no sean una IP
                return real
    except ValueError:
        pass
    return peer


def too_many(retry_after: int, detail: str = "Demasiados intentos. Espera unos minutos e inténtalo de nuevo.") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=detail,
        headers={"Retry-After": str(retry_after)},
    )


def rate_limit(name: str, max_requests: int, window_seconds: int) -> Callable:
    """Dependencia de FastAPI: maximo `max_requests` por IP y por `window_seconds` en el grupo `name`."""

    def dependency(request: Request) -> None:
        key = f"{name}:{client_ip(request)}"
        if limiter.count(key, window_seconds) >= max_requests:
            raise too_many(limiter.retry_after(key, window_seconds))
        limiter.hit(key, window_seconds)

    return dependency


# ----- Bloqueo por intentos de login fallidos -----
LOGIN_WINDOW = 15 * 60
LOGIN_MAX_PER_ACCOUNT_AND_IP = 5     # misma cuenta desde la misma IP
LOGIN_MAX_PER_IP = 20                # cualquier cuenta desde la misma IP


def login_blocked_for(email: str, ip: str) -> int:
    """Segundos de bloqueo restantes (0 = puede intentar)."""
    pair, by_ip = f"login:{ip}:{email}", f"login-ip:{ip}"
    if limiter.count(pair, LOGIN_WINDOW) >= LOGIN_MAX_PER_ACCOUNT_AND_IP:
        return limiter.retry_after(pair, LOGIN_WINDOW)
    if limiter.count(by_ip, LOGIN_WINDOW) >= LOGIN_MAX_PER_IP:
        return limiter.retry_after(by_ip, LOGIN_WINDOW)
    return 0


def login_failed(email: str, ip: str) -> None:
    limiter.hit(f"login:{ip}:{email}", LOGIN_WINDOW)
    limiter.hit(f"login-ip:{ip}", LOGIN_WINDOW)


def login_succeeded(email: str, ip: str) -> None:
    # El bloqueo es por (cuenta, IP): un atacante no puede bloquear al usuario legitimo desde otra IP.
    limiter.reset(f"login:{ip}:{email}")
