from .base import *

DEBUG = False

DATABASES = {
    "default": {
        "ENGINE":   "django.db.backends.postgresql",
        "NAME":     env("DB_NAME"),
        "USER":     env("DB_USER"),
        "PASSWORD": env("DB_PASSWORD"),
        "HOST":     env("DB_HOST", default="db"),
        "PORT":     env("DB_PORT", default="5432"),
        # Reuse each connection for up to 60s instead of reconnecting every
        # request — removes the per-request Postgres handshake overhead.
        "CONN_MAX_AGE": env.int("CONN_MAX_AGE", default=60),
        # Required companion to CONN_MAX_AGE: verify a reused connection is still
        # alive at the start of each request and transparently reconnect if the
        # DB dropped it (idle timeout, restart), instead of erroring mid-request.
        "CONN_HEALTH_CHECKS": True,
    }
}
