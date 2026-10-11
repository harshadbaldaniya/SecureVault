from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from core.views import HealthView

urlpatterns = [
    path("api/v1/health/", HealthView.as_view(), name="health"),
    path("api/v1/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/v1/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/v1/", include("apps.accounts.urls")),
    path("api/v1/", include("apps.departments.urls")),
    path("api/v1/", include("apps.services_catalog.urls")),
    path("api/v1/", include("apps.policies.urls")),
    path("api/v1/", include("apps.audit.urls")),
    path("api/v1/vault/", include("apps.vault.urls")),
    path("api/v1/", include("apps.sharing.urls")),
    path("api/v1/", include("apps.access_requests.urls")),
    path("api/v1/", include("apps.notifications.urls")),
]
