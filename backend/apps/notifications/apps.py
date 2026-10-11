from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    name = "apps.notifications"
    label = "notifications"

    def ready(self):
        from core.realtime import push_to_user

        from .services import register_push_hook

        def push(created):
            for n in created:
                push_to_user(
                    n.recipient_id,
                    {
                        "type": "notification",
                        "notification": {
                            "id": str(n.pk),
                            "type": n.type,
                            "priority": n.priority,
                            "title": n.title,
                            "message": n.message,
                            "link": n.link,
                            "created_at": n.created_at.isoformat(),
                        },
                    },
                )

        register_push_hook(push)
