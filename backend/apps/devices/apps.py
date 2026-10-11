from django.apps import AppConfig


class DevicesConfig(AppConfig):
    name = "apps.devices"
    label = "devices"

    def ready(self):
        from core.access_gate import register_check

        from .checks import anomaly_hold_check, device_trust_check

        # Order follows the zero-trust pipeline: device trust (6), anomaly policy (7); lockdown (8) registers later.
        register_check(device_trust_check)
        register_check(anomaly_hold_check)
