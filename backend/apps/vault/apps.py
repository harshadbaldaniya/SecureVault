from django.apps import AppConfig


class VaultConfig(AppConfig):
    name = "apps.vault"
    label = "vault"

    def ready(self):
        from .keys import validate_key_separation

        # Daphne does not run Django's system checks, so validate eagerly here (every entry point).
        validate_key_separation()
