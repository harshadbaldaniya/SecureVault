import io

from django.conf import settings
from django.http import HttpResponse
from drf_spectacular.utils import OpenApiResponse, extend_schema
from openpyxl import Workbook
from openpyxl.styles import Font
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.response import Response

from core.permissions import Perm, requires

from . import services
from .models import ImportJob


class ImportJobSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.CharField(source="uploaded_by.full_name", read_only=True)

    class Meta:
        model = ImportJob
        fields = [
            "id",
            "file_name",
            "status",
            "total_rows",
            "success_count",
            "failed_count",
            "errors",
            "file_error",
            "uploaded_by_name",
            "retry_of",
            "created_at",
            "started_at",
            "finished_at",
        ]
        read_only_fields = fields


class UploadSerializer(serializers.Serializer):
    file = serializers.FileField()


class ImportJobViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Bulk employee onboarding from Excel. Organization administrators only."""

    queryset = ImportJob.objects.none()
    serializer_class = ImportJobSerializer
    permission_classes = [requires(Perm.INVITATIONS_MANAGE)]
    parser_classes = [MultiPartParser, JSONParser]
    filterset_fields = ["status"]

    def get_queryset(self):
        return ImportJob.objects.filter(organization=self.request.user.organization).select_related("uploaded_by")

    @extend_schema(request={"multipart/form-data": UploadSerializer}, responses={201: ImportJobSerializer})
    def create(self, request):
        body = UploadSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        upload = body.validated_data["file"]
        if upload.size > settings.IMPORT_MAX_BYTES:
            return Response(
                {"error": {"code": "file_too_large", "message": "The file is larger than the upload limit."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        job = services.start_import(actor=request.user, file_name=upload.name, data=upload.read())
        return Response(ImportJobSerializer(job).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses={201: ImportJobSerializer})
    @action(detail=True, methods=["post"])
    def retry(self, request, pk=None):
        job = services.retry_failed(actor=request.user, job=self.get_object())
        return Response(ImportJobSerializer(job).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        responses={
            (200, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"): OpenApiResponse(
                description="Template"
            )
        }
    )
    @action(detail=False, methods=["get"])
    def template(self, request):
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Employees"
        sheet.append(["email", "full_name", "department", "role"])
        sheet.append(["jane.doe@example.com", "Jane Doe", "ENG", "EMPLOYEE"])
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        for column, width in zip("ABCD", (34, 26, 14, 12), strict=True):
            sheet.column_dimensions[column].width = width
        buffer = io.BytesIO()
        workbook.save(buffer)
        response = HttpResponse(
            buffer.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response["Content-Disposition"] = 'attachment; filename="securevault-employee-import-template.xlsx"'
        return response
