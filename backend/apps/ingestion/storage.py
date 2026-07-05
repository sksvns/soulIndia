"""Thin wrapper over boto3's S3 client. Every uploaded file is stored under
an immutable, uniquely-named key -- re-upload never overwrites a previous
file (see ADR-0002: corrections replace fact rows, never raw files).

Same client code targets MinIO in dev and Cloudflare R2 / Backblaze B2 in
prod -- only OBJECT_STORAGE_* env vars change.
"""

import uuid
from datetime import datetime, timezone

import boto3
from botocore.client import Config
from django.conf import settings


def _client():
    return boto3.client(
        "s3",
        endpoint_url=settings.OBJECT_STORAGE_ENDPOINT_URL,
        aws_access_key_id=settings.OBJECT_STORAGE_ACCESS_KEY,
        aws_secret_access_key=settings.OBJECT_STORAGE_SECRET_KEY,
        region_name=settings.OBJECT_STORAGE_REGION,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def build_upload_key(brand_code: str, product_line: str, original_filename: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    unique = uuid.uuid4().hex
    prefix = f"uploads/{brand_code.lower()}/{product_line}"
    return f"{prefix}/{timestamp}_{unique}_{original_filename}"


def put(key: str, fileobj, content_type: str | None = None) -> None:
    extra_args = {"ContentType": content_type} if content_type else {}
    _client().upload_fileobj(fileobj, settings.OBJECT_STORAGE_BUCKET, key, ExtraArgs=extra_args)


def get(key: str):
    response = _client().get_object(Bucket=settings.OBJECT_STORAGE_BUCKET, Key=key)
    return response["Body"]


def presigned_url(key: str, expires_in: int = 3600) -> str:
    return _client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.OBJECT_STORAGE_BUCKET, "Key": key},
        ExpiresIn=expires_in,
    )
