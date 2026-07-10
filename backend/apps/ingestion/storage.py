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
    kwargs = {
        "region_name": settings.OBJECT_STORAGE_REGION,
        "config": Config(
            signature_version="s3v4",
            s3={"addressing_style": settings.OBJECT_STORAGE_ADDRESSING_STYLE},
        ),
    }
    # Omit rather than pass None/empty -- boto3 only falls back to its own
    # endpoint resolution (real AWS S3) and default credential chain (IAM
    # instance role, no static keys) when these kwargs are absent entirely,
    # not just falsy.
    if settings.OBJECT_STORAGE_ENDPOINT_URL:
        kwargs["endpoint_url"] = settings.OBJECT_STORAGE_ENDPOINT_URL
    if settings.OBJECT_STORAGE_ACCESS_KEY:
        kwargs["aws_access_key_id"] = settings.OBJECT_STORAGE_ACCESS_KEY
        kwargs["aws_secret_access_key"] = settings.OBJECT_STORAGE_SECRET_KEY
    return boto3.client("s3", **kwargs)


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


def list_keys(prefix: str) -> list[str]:
    """Used by manage.py backup_database for retention cleanup -- lists
    every object under a prefix, paginating past S3's 1000-key-per-call cap."""
    client = _client()
    keys = []
    continuation_token = None
    while True:
        kwargs = {"Bucket": settings.OBJECT_STORAGE_BUCKET, "Prefix": prefix}
        if continuation_token:
            kwargs["ContinuationToken"] = continuation_token
        response = client.list_objects_v2(**kwargs)
        keys.extend(obj["Key"] for obj in response.get("Contents", []))
        if not response.get("IsTruncated"):
            break
        continuation_token = response["NextContinuationToken"]
    return keys


def delete(key: str) -> None:
    _client().delete_object(Bucket=settings.OBJECT_STORAGE_BUCKET, Key=key)
