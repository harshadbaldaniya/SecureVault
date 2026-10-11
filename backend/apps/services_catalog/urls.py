from rest_framework.routers import DefaultRouter

from .views import ServiceCatalogViewSet

router = DefaultRouter(trailing_slash=True)
router.register("services", ServiceCatalogViewSet, basename="service")

urlpatterns = router.urls
