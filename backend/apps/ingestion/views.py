from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.masterdata.models import BrandUploadConfig, DimBrand

from . import storage
from .models import UploadBatch
from .permissions import DjangoModelPermissionsIncludingView
from .serializers import UploadBatchSerializer
from .tasks import process_upload_batch

ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls"}


class UploadCreateView(APIView):
    """Intake only: stores the raw file immutably, creates the batch, and
    enqueues the worker. Never reads file contents -- parsing happens in the
    Celery task (Day 5+), matching the architecture's upload/worker split.
    """

    queryset = UploadBatch.objects.all()
    permission_classes = [DjangoModelPermissionsIncludingView]
    parser_classes = [MultiPartParser]

    def post(self, request):
        uploaded_file = request.FILES.get("file")
        brand_code = request.data.get("brand_code", "")
        product_line = request.data.get("product_line", "")

        if not uploaded_file or not brand_code or not product_line:
            return Response(
                {"detail": "file, brand_code and product_line are all required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        extension = (
            "." + uploaded_file.name.rsplit(".", 1)[-1].lower() if "." in uploaded_file.name else ""
        )
        if extension not in ALLOWED_EXTENSIONS:
            return Response(
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
        process_upload_batch.delay(batch.batch_id)

        return Response(UploadBatchSerializer(batch).data, status=status.HTTP_201_CREATED)


class UploadDetailView(APIView):
    """Polled by the client to track batch progress."""

    queryset = UploadBatch.objects.all()
    permission_classes = [DjangoModelPermissionsIncludingView]

    def get(self, request, batch_id):
        batch = get_object_or_404(UploadBatch, pk=batch_id)
        return Response(UploadBatchSerializer(batch).data)
