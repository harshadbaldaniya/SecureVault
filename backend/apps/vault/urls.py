from rest_framework.routers import SimpleRouter

from .views import CredentialViewSet, NoteViewSet

router = SimpleRouter(trailing_slash=True)
router.register("credentials", CredentialViewSet, basename="credential")
router.register("notes", NoteViewSet, basename="note")

urlpatterns = router.urls
