"""Email delivery that cannot change the outcome of the request that triggered it.

A failure to deliver (SMTP down, relay refusing, DNS) is logged and reported to the caller as False; it never
propagates. That matters for two reasons: the password-reset endpoint must answer identically for known and unknown
accounts (an error only for real accounts would reveal which exist), and an import that has already created its
invitations should not be reported as failed because a mail relay hiccuped. Invitations can be re-sent from the
Invitations page, which also shows the one-time link for out-of-band delivery.

Only the exception's class name is logged: SMTP error text can contain recipient addresses, and the message body
contains a one-time link that must never reach a log.
"""

import logging
from collections.abc import Sequence

from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def send_safely(subject: str, body: str, recipients: Sequence[str]) -> bool:
    try:
        send_mail(subject, body, None, list(recipients))
    except Exception as exc:  # delivery can fail in many library-specific ways; none may escape
        logger.error("Email delivery failed (%s); the request continues", type(exc).__name__)
        return False
    return True
