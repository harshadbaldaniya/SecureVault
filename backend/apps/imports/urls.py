from rest_framework.routers import SimpleRouter

from .views import ImportJobViewSet

router = SimpleRouter(trailing_slash=True)
router.register("imports", ImportJobViewSet, basename="import")

urlpatterns = router.urls
