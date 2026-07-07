import io
import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.ingestion import storage
from apps.ingestion.backfill import execute_backfill
from apps.ingestion.models import UploadBatch
from apps.masterdata.models import BrandUploadConfig, DimBrand

User = get_user_model()


class Command(BaseCommand):
    help = (
        "One-time historical backfill for a (brand, product_line) file: loads "
        "every row that passes Phase A validation, writes every row that "
        "doesn't to a CSV (row_no, field, value, reason). Deliberately "
        "separate from the regular upload API, which stays all-or-nothing "
        "per plan.md Day 5 -- see apps/ingestion/backfill.py. Same "
        "orchestration as POST /api/ingestion/backfill/, just synchronous "
        "and CLI-driven."
    )

    def add_arguments(self, parser):
        parser.add_argument("brand_code")
        parser.add_argument("product_line")
        parser.add_argument("file_path")
        parser.add_argument(
            "--user-email",
            required=True,
            help="Existing user this backfill is attributed to (audit trail).",
        )
        parser.add_argument(
            "--csv-out",
            help="Also write the bad-rows CSV to this local path, in addition "
            "to object storage.",
        )

    def handle(self, *args, **options):
        brand_code = options["brand_code"].upper()
        product_line = options["product_line"]
        file_path = options["file_path"]

        try:
            brand = DimBrand.objects.get(brand_code=brand_code, active=True)
        except DimBrand.DoesNotExist as exc:
            raise CommandError(f"no active brand '{brand_code}'") from exc

        try:
            config = BrandUploadConfig.objects.get(
                brand=brand, product_line=product_line, active=True
            )
        except BrandUploadConfig.DoesNotExist as exc:
            raise CommandError(f"no active upload config for {brand_code}/{product_line}") from exc

        try:
            user = User.objects.get(email__iexact=options["user_email"])
        except User.DoesNotExist as exc:
            raise CommandError(f"no user with email '{options['user_email']}'") from exc

        if not os.path.exists(file_path):
            raise CommandError(f"file not found: {file_path}")

        with open(file_path, "rb") as f:
            raw_bytes = f.read()
        filename = os.path.basename(file_path)

        object_key = storage.build_upload_key(brand_code, product_line, filename)
        storage.put(object_key, io.BytesIO(raw_bytes), content_type="application/octet-stream")

        batch = UploadBatch.objects.create(
            brand=brand,
            config=config,
            uploaded_by=user,
            file_name=filename,
            object_key=object_key,
            status=UploadBatch.Status.VALIDATING,
            started_at=timezone.now(),
        )
        self.stdout.write(f"batch #{batch.batch_id}: parsing + validating {filename}...")

        result = execute_backfill(batch)

        if options["csv_out"] and batch.error_report_key:
            report_bytes = storage.get(batch.error_report_key).read()
            with open(options["csv_out"], "wb") as f:
                f.write(report_bytes)
            self.stdout.write(f"bad-rows CSV written to {options['csv_out']}")

        if batch.status == UploadBatch.Status.FAILED:
            reason = batch.failure_reason or (
                f"no valid rows out of {result.total_rows} -- nothing loaded"
            )
            raise CommandError(f"{reason} (see {batch.error_report_key})")

        self.stdout.write(
            self.style.SUCCESS(
                f"batch #{batch.batch_id}: loaded {len(result.valid_rows)}/{result.total_rows} "
                f"row(s) across {len(batch.slices)} slice(s); {len(result.errors)} row(s) rejected"
                + (f", see {batch.error_report_key}" if batch.error_report_key else "")
            )
        )
