from io import StringIO

import pytest
from django.core.management import call_command

from apps.ingestion.models import UploadBatch
from apps.ingestion.tasks import process_upload_batch
from apps.masterdata.models import BrandUploadConfig, DimBrand


@pytest.mark.django_db
def test_process_upload_batch_transitions_status_to_parsing(data_inserter_user):
    call_command("seed_brands", stdout=StringIO())
    call_command("seed_upload_configs", stdout=StringIO())
    brand = DimBrand.objects.get(brand_code="KILLER")
    config = BrandUploadConfig.objects.get(brand=brand)
    batch = UploadBatch.objects.create(
        brand=brand,
        config=config,
        uploaded_by=data_inserter_user,
        file_name="april.csv",
        object_key="uploads/killer/menswear/test.csv",
    )
    assert batch.status == UploadBatch.Status.RECEIVED
    assert batch.started_at is None

    process_upload_batch(batch.batch_id)

    batch.refresh_from_db()
    assert batch.status == UploadBatch.Status.PARSING
    assert batch.started_at is not None
