import pytest

from apps.notifications.models import Notification
from apps.notifications.services import notify

pytestmark = pytest.mark.django_db

URL = "/api/v1/notifications/"


def test_users_see_only_their_own_notifications(client_for, employee, make_user):
    other = make_user()
    notify([employee], "SHARE_CREATED", "For Eve")
    notify([other], "SHARE_CREATED", "For someone else")
    titles = [n["title"] for n in client_for(employee).get(URL).json()["results"]]
    assert titles == ["For Eve"]


def test_unread_count_mark_read_and_read_all(client_for, employee):
    created = notify([employee], "SHARE_CREATED", "One") + notify([employee], "SHARE_REVOKED", "Two")
    client = client_for(employee)
    assert client.get(f"{URL}unread-count/").json() == {"unread": 2}
    marked = client.post(f"{URL}{created[0].pk}/read/").json()
    assert marked["is_read"] is True and marked["read_at"] is not None
    assert client.get(f"{URL}unread-count/").json() == {"unread": 1}
    assert client.post(f"{URL}read-all/").json() == {"updated": 1}
    assert client.get(URL, {"is_read": "false"}).json()["count"] == 0


def test_cannot_touch_someone_elses_notification(client_for, employee, make_user):
    theirs = notify([make_user()], "SHARE_CREATED", "Private")[0]
    assert client_for(employee).post(f"{URL}{theirs.pk}/read/").status_code == 404
    assert Notification.objects.get(pk=theirs.pk).is_read is False


def test_notify_deduplicates_recipients_and_skips_none(employee):
    created = notify([employee, employee, None], "LOCKDOWN", "Once")
    assert len(created) == 1
