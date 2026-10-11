from rest_framework.routers import DefaultRouter

from .views import DepartmentViewSet

router = DefaultRouter(trailing_slash=True)
router.register("departments", DepartmentViewSet, basename="department")

urlpatterns = router.urls
