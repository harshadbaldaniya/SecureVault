from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver

from . import services


@receiver(user_logged_in)
def on_login(sender, request, user, **kwargs):
    # login() has already rotated the session key (session-fixation protection).
    services.record_session(request, user)


@receiver(user_logged_out)
def on_logout(sender, request, user, **kwargs):
    services.forget_session(request.session.session_key)
