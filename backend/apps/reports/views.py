"""Report endpoints: JSON for the UI (paginated), CSV / XLSX / PDF for export (capped, audited)."""

from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit import services as audit
from apps.audit.models import AuditAction
from core.exceptions import ServiceError
from core.permissions import Perm, requires

from . import exporters
from .datasets import DATASETS, Dataset, FilterError, parse_filters

FORMATS = {
    "csv": ("text/csv; charset=utf-8", "csv"),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
    "pdf": ("application/pdf", "pdf"),
}
PDF_MAX_ROWS = 2_000


def _dataset(key: str) -> Dataset:
    dataset = DATASETS.get(key)
    if dataset is None:
        raise ServiceError("Unknown report.", "unknown_report", status_code=404)
    return dataset


def _columns(dataset: Dataset, requested) -> list:
    if not requested:
        return list(dataset.columns)
    keys = requested.split(",") if isinstance(requested, str) else list(requested)
    keys = [k.strip() for k in keys if k and k.strip()]
    if not keys:
        return list(dataset.columns)
    try:
        return [dataset.column(k) for k in keys]
    except FilterError as exc:
        raise ServiceError(str(exc), "invalid_column") from None


def _render(request, dataset: Dataset, source, requested_columns, output_format: str):
    try:
        filters = parse_filters(source, dataset)
    except FilterError as exc:
        raise ServiceError(str(exc), "invalid_filter") from None
    columns = _columns(dataset, requested_columns)
    organization = request.user.organization
    queryset = dataset.apply(dataset.base(organization), filters, organization)

    if output_format in ("", "json"):
        try:
            page = max(int(source.get("page", 1)), 1)
            page_size = min(max(int(source.get("page_size", 50)), 1), 200)
        except (TypeError, ValueError):
            raise ServiceError("page and page_size must be numbers.", "invalid_filter") from None
        total = queryset.count()
        rows = queryset[(page - 1) * page_size : page * page_size]
        return Response(
            {
                "report": dataset.key,
                "title": dataset.title,
                "columns": [{"key": c.key, "label": c.label} for c in columns],
                "count": total,
                "page": page,
                "results": [{c.key: c.get(row) for c in columns} for row in rows],
            }
        )

    if output_format not in FORMATS:
        raise ServiceError("format must be json, csv, xlsx or pdf.", "invalid_format")
    limit = (
        settings.REPORT_EXPORT_MAX_ROWS
        if output_format != "pdf"
        else min(PDF_MAX_ROWS, settings.REPORT_EXPORT_MAX_ROWS)
    )
    total = queryset.count()
    rows = [[c.get(row) for c in columns] for row in queryset[:limit]]
    headers = [c.label for c in columns]
    truncated = total > limit
    stamp = timezone.now()
    note = (
        f"Showing the first {limit:,} of {total:,} rows. Narrow the filters to export everything." if truncated else ""
    )

    if output_format == "csv":
        body = exporters.to_csv(headers, rows)
    elif output_format == "xlsx":
        body = exporters.to_xlsx(dataset.title, headers, rows)
    else:
        subtitle = f"{request.user.organization.name} - generated {stamp:%Y-%m-%d %H:%M} UTC by {request.user.email}"
        if filters.describe():
            subtitle += " - filters: " + ", ".join(f"{k}={v}" for k, v in filters.describe().items())
        body = exporters.to_pdf(dataset.title, subtitle, headers, rows, note)

    audit.record(
        AuditAction.REPORT_EXPORT,
        actor=request.user,
        target_type="report",
        target_label=dataset.key,
        metadata={
            "report": dataset.key,
            "format": output_format,
            "rows": len(rows),
            "total": total,
            "columns": [c.key for c in columns],
            "filters": filters.describe(),
        },
    )
    content_type, extension = FORMATS[output_format]
    response = HttpResponse(body, content_type=content_type)
    response["Content-Disposition"] = (
        f'attachment; filename="securevault-{dataset.key}-{stamp:%Y%m%d-%H%M}.{extension}"'
    )
    response["Cache-Control"] = "no-store"
    response["X-Report-Truncated"] = "true" if truncated else "false"
    return response


_FILTER_PARAMS = [
    OpenApiParameter(name, str)
    for name in (
        "department",
        "date_from",
        "date_to",
        "user",
        "service",
        "resource",
        "device_trust",
        "share_status",
        "status",
        "columns",
        "page",
        "page_size",
    )
] + [
    OpenApiParameter("action", str, many=True),
    OpenApiParameter("format", str, enum=["json", "csv", "xlsx", "pdf"]),
]

_REPORT_RESPONSE = inline_serializer(
    "ReportPage",
    {
        "report": serializers.CharField(),
        "title": serializers.CharField(),
        "columns": serializers.ListField(child=serializers.DictField()),
        "count": serializers.IntegerField(),
        "page": serializers.IntegerField(),
        "results": serializers.ListField(child=serializers.DictField()),
    },
)


class ReportCatalogView(APIView):
    """Available reports with their columns and supported filters (drives the report builder UI)."""

    permission_classes = [requires(Perm.REPORTS_VIEW)]

    @extend_schema(
        operation_id="reports_catalog",
        responses={
            200: inline_serializer("ReportCatalog", {"reports": serializers.ListField(child=serializers.DictField())})
        },
    )
    def get(self, request):
        return Response(
            {
                "reports": [
                    {
                        "key": d.key,
                        "title": d.title,
                        "description": d.description,
                        "columns": [{"key": c.key, "label": c.label} for c in d.columns],
                        "filters": sorted(d.filters),
                        "statuses": sorted(d.statuses),
                    }
                    for d in DATASETS.values()
                ]
            }
        )


class ReportView(APIView):
    permission_classes = [requires(Perm.REPORTS_VIEW)]

    @extend_schema(operation_id="reports_run", parameters=_FILTER_PARAMS, responses={200: _REPORT_RESPONSE})
    def get(self, request, key):
        return _render(
            request,
            _dataset(key),
            request.query_params,
            request.query_params.get("columns"),
            request.query_params.get("format", "json").lower(),
        )


class CustomReportSerializer(serializers.Serializer):
    dataset = serializers.ChoiceField(choices=sorted(DATASETS))
    columns = serializers.ListField(child=serializers.CharField(max_length=40), min_length=1, max_length=30)
    filters = serializers.DictField(required=False, default=dict)
    format = serializers.ChoiceField(choices=["json", "csv", "xlsx", "pdf"], default="json")


class CustomReportView(APIView):
    """Report builder: any allow-listed columns of one dataset, with that dataset's filters."""

    permission_classes = [requires(Perm.REPORTS_VIEW)]

    @extend_schema(request=CustomReportSerializer, responses={200: _REPORT_RESPONSE})
    def post(self, request):
        body = CustomReportSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        source = {**data["filters"], "page": request.query_params.get("page", 1)}
        return _render(request, _dataset(data["dataset"]), source, data["columns"], data["format"])
