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
    }
}
