from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import CredentialDirectoryView, CredentialViewSet, NoteViewSet

router = SimpleRouter(trailing_slash=True)
router.register("credentials", CredentialViewSet, basename="credential")
router.register("notes", NoteViewSet, basename="note")

urlpatterns = [
    path("directory/", CredentialDirectoryView.as_view(), name="credential-directory"),
    *router.urls,
]
