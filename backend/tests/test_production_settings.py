"""Production configuration, checked by starting Django in a subprocess with a controlled environment.

Settings are read once at import time, so each case needs a fresh interpreter. The environment is built from
scratch (random keys per run); nothing here depends on the developer's .env, whose values are only loaded for
variables that are not already set.
"""

import base64
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]


def _key() -> str:
    return "1:" + base64.urlsafe_b64encode(os.urandom(32)).decode()


def production_env(**overrides) -> dict:
    env = {
        # Keep the interpreter working on Windows (SYSTEMROOT) and Linux (PATH, locale) without inheriting settings.
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "SYSTEMROOT", "TEMP", "TMP", "HOME", "USERPROFILE", "LANG", "LC_ALL"}
    }
    env.update(
        SV_ENV_FILE=os.devnull,  # hermetic: never read the developer's .env
        DJANGO_SETTINGS_MODULE="config.settings",
        DJANGO_DEBUG="false",
        DJANGO_SECRET_KEY=secrets.token_urlsafe(64),
        DJANGO_ALLOWED_HOSTS="vault.example.test",
        POSTGRES_PASSWORD=secrets.token_urlsafe(24),
        SV_MFA_ENCRYPTION_KEYS=_key(),
        SV_VAULT_KEK_KEYS=_key(),
        SV_BLIND_INDEX_KEYS=_key(),
    )
    env.update(overrides)
    return {key: value for key, value in env.items() if value is not None}


def run(env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603 - fixed interpreter and arguments
        [sys.executable, *args], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=120, check=False
    )


def settings_of(env: dict, *names: str) -> dict:
    code = (
        "import json, config.settings as s\n"
        f"print(json.dumps({{name: getattr(s, name) for name in {list(names)!r}}}, default=str))"
    )
    result = run(env, "-c", code)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_production_defaults_are_secure():
    values = settings_of(
        production_env(),
        "DEBUG",
        "SESSION_COOKIE_SECURE",
        "CSRF_COOKIE_SECURE",
        "SESSION_COOKIE_SAMESITE",
        "SESSION_COOKIE_HTTPONLY",
        "SECURE_SSL_REDIRECT",
        "SECURE_HSTS_SECONDS",
        "SECURE_HSTS_INCLUDE_SUBDOMAINS",
        "ENABLE_API_DOCS",
        "METRICS_TOKEN",
        "LOG_JSON",
        "SECURE_REDIRECT_EXEMPT",
    )
    assert values == {
        "DEBUG": False,
        "SESSION_COOKIE_SECURE": True,
        "CSRF_COOKIE_SECURE": True,
        "SESSION_COOKIE_SAMESITE": "Strict",
        "SESSION_COOKIE_HTTPONLY": True,
        "SECURE_SSL_REDIRECT": True,
        "SECURE_HSTS_SECONDS": 31536000,
        "SECURE_HSTS_INCLUDE_SUBDOMAINS": True,
        "ENABLE_API_DOCS": False,  # API docs and the metrics endpoint are opt-in in production
        "METRICS_TOKEN": "",
        "LOG_JSON": True,
        "SECURE_REDIRECT_EXEMPT": ["^api/v1/health/$", "^api/v1/metrics/$"],
    }


def test_production_uses_the_connection_pool_and_development_does_not():
    prod = settings_of(production_env(), "DATABASES")["DATABASES"]["default"]
    assert prod["CONN_MAX_AGE"] == 0  # Django refuses pooling with persistent connections
    assert prod["OPTIONS"]["pool"] == {"min_size": 2, "max_size": 10, "timeout": 10.0, "max_lifetime": 1800}

    dev = settings_of(production_env(DJANGO_DEBUG="true"), "DATABASES", "ENABLE_API_DOCS", "LOG_JSON")
    assert dev["DATABASES"]["default"]["CONN_MAX_AGE"] == 0 and "pool" not in dev["DATABASES"]["default"]["OPTIONS"]
    assert dev["ENABLE_API_DOCS"] is True and dev["LOG_JSON"] is False

    tuned = settings_of(production_env(SV_DB_POOL_MAX="25", SV_DB_POOL_TIMEOUT="3"), "DATABASES")
    assert tuned["DATABASES"]["default"]["OPTIONS"]["pool"]["max_size"] == 25


def test_the_api_renders_and_accepts_json_only():
    values = settings_of(production_env(), "REST_FRAMEWORK")["REST_FRAMEWORK"]
    assert values["DEFAULT_RENDERER_CLASSES"] == ["rest_framework.renderers.JSONRenderer"]
    assert values["DEFAULT_PARSER_CLASSES"] == ["rest_framework.parsers.JSONParser"]


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"DJANGO_SECRET_KEY": "change-me"}, "DJANGO_SECRET_KEY"),
        ({"DJANGO_SECRET_KEY": "short"}, "DJANGO_SECRET_KEY"),
        ({"DJANGO_SECRET_KEY": None}, "DJANGO_SECRET_KEY"),
        ({"POSTGRES_PASSWORD": None}, "POSTGRES_PASSWORD"),
        ({"SV_VAULT_KEK_KEYS": None}, "SV_VAULT_KEK_KEYS"),
        ({"SV_METRICS_TOKEN": "too-short"}, "SV_METRICS_TOKEN"),
    ],
)
def test_misconfiguration_stops_startup_with_a_clear_message(override, message):
    result = run(production_env(**override), "-c", "import config.settings")
    assert result.returncode != 0
    assert "ImproperlyConfigured" in result.stderr and message in result.stderr


def test_the_same_key_cannot_serve_two_purposes():
    shared = _key()
    env = production_env(SV_VAULT_KEK_KEYS=shared, SV_BLIND_INDEX_KEYS=shared)
    result = run(env, "manage.py", "check")
    assert result.returncode != 0 and "must not share key material" in (result.stderr + result.stdout)


def test_django_deployment_checklist_has_no_warnings():
    # security.W021 (HSTS preload) is deliberately not satisfied: preloading commits a domain to browsers' lists
    # for months and must be an explicit decision of the domain owner. It is silenced in settings with that reason.
    result = run(production_env(), "manage.py", "check", "--deploy", "--fail-level", "WARNING")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "no issues" in result.stdout
