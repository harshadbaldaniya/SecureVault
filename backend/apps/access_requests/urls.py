from rest_framework.routers import SimpleRouter

from .views import AccessRequestViewSet

router = SimpleRouter(trailing_slash=True)
router.register("access-requests", AccessRequestViewSet, basename="access-request")

urlpatterns = router.urls
