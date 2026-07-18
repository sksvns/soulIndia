import logging
import re

from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.masterdata.models import BrandUploadConfig, DimBrand

from . import storage
from .loader import DataAlterationNotPermitted, delete_by_filter, preview_delete
from .models import UploadBatch
from .permissions import DjangoModelPermissionsIncludingView
from .serializers import UploadBatchSerializer
from .tasks import process_upload_batch

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

FINANCIAL_YEAR_RE = re.compile(r"^\d{2}-\d{2}$")

DELETE_REQUEST_SERIALIZER = inline_serializer(
    "DeleteDataRequest",
    {
        "brand_code": serializers.CharField(help_text="e.g. KILLER, PEPE"),
        "product_line": serializers.CharField(help_text="e.g. menswear"),
        "financial_year": serializers.CharField(help_text="e.g. 25-26"),
        "month": serializers.IntegerField(help_text="1-12"),
    },
)

DELETE_PREVIEW_RESPONSE_SERIALIZER = inline_serializer(
    "DeletePreviewResponse",
    {
        "row_count": serializers.IntegerField(),
        "store_count": serializers.IntegerField(),
        "total_net_value": serializers.DecimalField(
            max_digits=16, decimal_places=2, allow_null=True
        ),
        "min_date": serializers.DateField(allow_null=True),
        "max_date": serializers.DateField(allow_null=True),
    },
)

DELETE_RESPONSE_SERIALIZER = inline_serializer(
    "DeleteDataResponse", {"deleted_count": serializers.IntegerField()}
)


def _resolve_delete_target(params):
    """Shared brand/product_line/financial_year/month resolution +
    validation for the Delete Data preview and delete endpoints -- both
    must scope to the exact same target, so they share one resolver rather
    than parsing independently and risking the two drifting apart.

    Returns (target, None) on success, where target is
    (brand, product_line, financial_year, month_no), or (None, error_response)
    on a request-shape problem.
    """
    brand_code = params.get("brand_code", "")
    product_line = params.get("product_line", "")
    financial_year = params.get("financial_year", "")
    month_raw = params.get("month", "")

    if not brand_code or not product_line or not financial_year or not month_raw:
        return None, Response(
            {"detail": "brand_code, product_line, financial_year and month are all required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if not FINANCIAL_YEAR_RE.match(financial_year):
        return None, Response(
            {"detail": f"financial_year must look like '25-26', got '{financial_year}'"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        month_no = int(month_raw)
    except (TypeError, ValueError):
        return None, Response(
            {"detail": f"month must be an integer 1-12, got '{month_raw}'"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not 1 <= month_no <= 12:
        return None, Response(
            {"detail": f"month must be an integer 1-12, got {month_no}"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    brand = get_object_or_404(DimBrand, brand_code=brand_code.upper(), active=True)
    get_object_or_404(BrandUploadConfig, brand=brand, product_line=product_line, active=True)

    return (brand, product_line, financial_year, month_no), None


def _intake_upload(request):
    """Shared file/brand/config validation + immutable raw-file storage for
    both the regular upload and backfill endpoints -- both now run the
    exact same load-good-report-bad processing (apps.ingestion.tasks.
    process_upload_batch); the only real difference left between the two
    endpoints is /backfill/'s Super-Admin permission requirement.

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
    """Historically a separate Super-Admin-only path for one-time backfill
    (apps.ingestion.backfill, ADR-0005); the regular /uploads/ endpoint now
    runs the exact same load-good-report-bad processing for every upload,
    so this endpoint is behaviorally identical to it today, just still
    gated behind ingestion.alter_existing_data (Super Admin). Kept as a
    distinct URL for anything already calling it directly rather than
    removed outright; a Data Inserter gets the same load-good-report-bad
    result from the regular /uploads/ endpoint without needing this
    permission at all.
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
        process_upload_batch.delay(batch.batch_id)

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


class DeletePreviewView(APIView):
    """Read-only summary (row count, store count, total net value, date
    range) of what a Delete Data request would remove -- powers the
    confirmation dialog's preview. Never alters anything, so never audited
    (ADR-0003 audits alterations, not reads); still requires authentication
    and view-level permission, same as every other endpoint here.
    """

    queryset = UploadBatch.objects.all()
    permission_classes = [DjangoModelPermissionsIncludingView]

    @extend_schema(
        parameters=[
            OpenApiParameter("brand_code", str),
            OpenApiParameter("product_line", str),
            OpenApiParameter("financial_year", str, description="e.g. 25-26"),
            OpenApiParameter("month", int, description="1-12"),
        ],
        responses=DELETE_PREVIEW_RESPONSE_SERIALIZER,
    )
    def get(self, request):
        target, error = _resolve_delete_target(request.query_params)
        if error:
            return error
        brand, product_line, financial_year, month_no = target

        preview = preview_delete(brand, product_line, financial_year, month_no)
        return Response(
            {
                "row_count": preview["row_count"],
                "store_count": preview["store_count"],
                "total_net_value": preview["total_net_value"],
                "min_date": preview["min_date"],
                "max_date": preview["max_date"],
            }
        )


class DeleteDataView(APIView):
    """Deletes every fact_sales row for one brand + product_line +
    financial_year + month (the Delete Data page), across however many
    upload batches loaded into that slice.

    Gated and audited exactly like batch rollback (ADR-0003):
    `delete_by_filter` itself decides allow/block and writes the audit
    record, so this view never short-circuits on permission before that
    happens -- an unauthorized attempt still has to show up in the audit
    trail, not just get a plain 403 with nothing recorded.
    """

    queryset = UploadBatch.objects.all()
    permission_classes = [DjangoModelPermissionsIncludingView]

    @extend_schema(request=DELETE_REQUEST_SERIALIZER, responses=DELETE_RESPONSE_SERIALIZER)
    def post(self, request):
        target, error = _resolve_delete_target(request.data)
        if error:
            return error
        brand, product_line, financial_year, month_no = target

        try:
            deleted_count = delete_by_filter(
                brand, product_line, financial_year, month_no, request.user
            )
        except DataAlterationNotPermitted as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)

        logger.info(
            "user %s deleted %s fact_sales row(s) for %s/%s FY%s month=%s",
            request.user.email,
            deleted_count,
            brand.brand_code,
            product_line,
            financial_year,
            month_no,
        )
        return Response({"deleted_count": deleted_count})
