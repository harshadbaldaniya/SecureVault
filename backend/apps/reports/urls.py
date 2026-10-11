from django.urls import path

from .dashboard import DashboardView
from .views import CustomReportView, ReportCatalogView, ReportView

urlpatterns = [
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
    path("reports/", ReportCatalogView.as_view(), name="report-catalog"),
    path("reports/custom/", CustomReportView.as_view(), name="report-custom"),
    path("reports/<slug:key>/", ReportView.as_view(), name="report"),
]
