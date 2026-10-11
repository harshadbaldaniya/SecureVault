from django.apps import AppConfig


class LockdownConfig(AppConfig):
    name = "apps.lockdown"
    label = "lockdown"

    def ready(self):
        from core.access_gate import register_check

        from .services import lockdown_check

        register_check(lockdown_check)  # pipeline step 8
