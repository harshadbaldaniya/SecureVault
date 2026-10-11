import uuid

from django.db import models


class TimeStampedModel(models.Model):
    """UUID primary key + created/updated timestamps for every domain model.

    UUIDs make IDs non-enumerable; they are NOT an access control. Every
    query must still be scoped to the caller's organization and permissions.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
