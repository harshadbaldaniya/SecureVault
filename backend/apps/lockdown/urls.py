from rest_framework.routers import SimpleRouter

from .views import LockdownViewSet

router = SimpleRouter(trailing_slash=True)
router.register("lockdown", LockdownViewSet, basename="lockdown")

urlpatterns = router.urls
