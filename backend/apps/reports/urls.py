from django.urls import path

from .views import CustomReportView, ReportCatalogView, ReportView

urlpatterns = [
    path("reports/", ReportCatalogView.as_view(), name="report-catalog"),
    path("reports/custom/", CustomReportView.as_view(), name="report-custom"),
    path("reports/<slug:key>/", ReportView.as_view(), name="report"),
]
