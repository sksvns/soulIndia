import logging

from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.masterdata.models import BrandUploadConfig, DimBrand

from . import storage
from .models import UploadBatch
from .permissions import DjangoModelPermissionsIncludingView
from .serializers import UploadBatchSerializer
from .tasks import process_backfill_batch, process_upload_batch

logger = logging.getLogger(__name__)

# .xlsb included alongside the plan's originally-specified CSV/XLSX/XLS --
# both real Killer/Pepe sample files turned out to actually be .xlsb
# (confirmed inspecting the real files during Day 0), which openpyxl can't
# read at all (see apps/ingestion/parsing.py).
ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls", ".xlsb"}

UPLOAD_REQUEST_SERIALIZER = inline_serializer(
    "UploadCreateRequest",
    {
        "file": serializers.FileField(),
        "brand_code": serializers.CharField(help_text="e.g. KILLER, PEPE"),
        "product_line": serializers.CharField(help_text="e.g. menswear"),
    },
)


def _intake_upload(request):
    """Shared file/brand/config validation + immutable raw-file storage for
    both the regular upload and backfill endpoints -- everything up to "a
    batch row exists and the raw bytes are safely in object storage" is
    identical between the two; only what happens *after* (all-or-nothing
    vs. load-good-report-bad) differs.

    Returns (batch, None) on success, or (None, error_response) on a
    request-shape problem (never touches the DB or storage in that case).
    """
    uploaded_file = request.FILES.get("file")
    brand_code = request.data.get("brand_code", "")
    product_line = request.data.get("product_line", "")

    if not uploaded_file or not brand_code or not product_line:
        return None, Response(
            {"detail": "file, brand_code and product_line are all required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    extension = (
        "." + uploaded_file.name.rsplit(".", 1)[-1].lower() if "." in uploaded_file.name else ""
    )
    if extension not in ALLOWED_EXTENSIONS:
        return None, Response(
            {
                "detail": (
                    f"unsupported file type '{extension}'; "
                    f"expected one of {sorted(ALLOWED_EXTENSIONS)}"
                )
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    brand = get_object_or_404(DimBrand, brand_code=brand_code.upper(), active=True)
    config = get_object_or_404(
        BrandUploadConfig, brand=brand, product_line=product_line, active=True
    )

    object_key = storage.build_upload_key(brand.brand_code, product_line, uploaded_file.name)
    storage.put(object_key, uploaded_file, content_type=uploaded_file.content_type)

    batch = UploadBatch.objects.create(
        brand=brand,
        config=config,
        uploaded_by=request.user,
        file_name=uploaded_file.name,
        object_key=object_key,
        status=UploadBatch.Status.RECEIVED,
    )
    return batch, None


class UploadCreateView(APIView):
    """Intake only: stores the raw file immutably, creates the batch, and
    enqueues the worker. Never reads file contents -- parsing happens in the
    Celery task (Day 5+), matching the architecture's upload/worker split.
    """

    queryset = UploadBatch.objects.all()
    permission_classes = [DjangoModelPermissionsIncludingView]
    parser_classes = [MultiPartParser]

    @extend_schema(request=UPLOAD_REQUEST_SERIALIZER, responses=UploadBatchSerializer)
    def post(self, request):
        batch, error = _intake_upload(request)
        if error:
            return error

        logger.info(
            "batch #%s: received %s for %s/%s from %s",
            batch.batch_id,
            batch.file_name,
            batch.brand.brand_code,
            batch.config.product_line,
            request.user.email,
        )
        process_upload_batch.delay(batch.batch_id)

        return Response(UploadBatchSerializer(batch).data, status=status.HTTP_201_CREATED)


class BackfillUploadView(APIView):
    """One-time historical backfill (apps.ingestion.backfill): same request
    shape as the regular upload, but loads every row that passes Phase A
    validation and reports the rest in a downloadable CSV, instead of
    failing the whole file on any error. Deliberately gated behind
    ingestion.alter_existing_data (Super Admin) -- this bypasses the
    all-or-nothing data-quality gate the regular endpoint always enforces,
    so triggering it is at least as sensitive as altering already-loaded
    data (ADR-0003), not a routine Data Inserter action.
    """

    queryset = UploadBatch.objects.all()
    permission_classes = [DjangoModelPermissionsIncludingView]
    parser_classes = [MultiPartParser]

    @extend_schema(request=UPLOAD_REQUEST_SERIALIZER, responses=UploadBatchSerializer)
    def post(self, request):
        if not request.user.has_perm("ingestion.alter_existing_data"):
            return HttpResponseForbidden(
                "Backfill requires Super Admin access (ingestion.alter_existing_data)."
            )

        batch, error = _intake_upload(request)
        if error:
            return error

        logger.info(
            "batch #%s: backfill received %s for %s/%s from %s",
            batch.batch_id,
            batch.file_name,
            batch.brand.brand_code,
            batch.config.product_line,
            request.user.email,
        )
        process_backfill_batch.delay(batch.batch_id)

        return Response(UploadBatchSerializer(batch).data, status=status.HTTP_201_CREATED)


class UploadDetailView(APIView):
    """Polled by the client to track batch progress."""

    queryset = UploadBatch.objects.all()
    permission_classes = [DjangoModelPermissionsIncludingView]

    @extend_schema(responses=UploadBatchSerializer)
    def get(self, request, batch_id):
        batch = get_object_or_404(UploadBatch, pk=batch_id)
        return Response(UploadBatchSerializer(batch).data)


class ErrorReportDownloadView(APIView):
    """Downloads a batch's bad-rows CSV (row_no, field, value, reason) --
    set on any failed regular upload and on any backfill with rejected
    rows. 404 if this batch has no report (nothing ever failed)."""

    queryset = UploadBatch.objects.all()
    permission_classes = [DjangoModelPermissionsIncludingView]

    @extend_schema(responses={200: OpenApiTypes.BINARY})
    def get(self, request, batch_id):
        batch = get_object_or_404(UploadBatch, pk=batch_id)
        if not batch.error_report_key:
            return Response(
                {"detail": "no error report for this batch"}, status=status.HTTP_404_NOT_FOUND
            )

        body = storage.get(batch.error_report_key).read()
        response = HttpResponse(body, content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="batch_{batch_id}_errors.csv"'
        return response
