from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from core.views import HealthView, MetricsView

urlpatterns = [
    path("api/v1/health/", HealthView.as_view(), name="health"),
    path("api/v1/metrics/", MetricsView.as_view(), name="metrics"),
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
    path("api/v1/", include("apps.devices.urls")),
    path("api/v1/", include("apps.lockdown.urls")),
    path("api/v1/", include("apps.imports.urls")),
    path("api/v1/", include("apps.reports.urls")),
]

# JSON instead of Django's HTML error pages (see core/views.py).
handler400 = "core.views.bad_request"
handler403 = "core.views.permission_denied"
handler404 = "core.views.not_found"
handler500 = "core.views.server_error"
