from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import AlertViewSet, CurrentDeviceView, DeviceViewSet, RegisterDeviceView

router = SimpleRouter(trailing_slash=True)
router.register("devices", DeviceViewSet, basename="device")
router.register("alerts", AlertViewSet, basename="alert")

urlpatterns = [
    path("devices/register/", RegisterDeviceView.as_view(), name="device-register"),
    path("devices/current/", CurrentDeviceView.as_view(), name="device-current"),
    *router.urls,
]
