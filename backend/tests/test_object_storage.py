import io

from apps.ingestion import storage


def test_client_omits_endpoint_and_credentials_when_unset(settings, monkeypatch):
    """Real AWS S3 needs boto3 to resolve its own regional endpoint, and an
    EC2 IAM instance role needs boto3's default credential chain -- both
    only happen when these kwargs are absent entirely, not passed as
    None/empty (which would override the defaults with "no endpoint" /
    "no credentials" instead of "figure it out yourself")."""
    settings.OBJECT_STORAGE_ENDPOINT_URL = None
    settings.OBJECT_STORAGE_ACCESS_KEY = None
    settings.OBJECT_STORAGE_SECRET_KEY = None
    captured = {}

    def fake_client(service, **kwargs):
        captured.update(kwargs)
        return None

    monkeypatch.setattr(storage.boto3, "client", fake_client)

    storage._client()

    assert "endpoint_url" not in captured
    assert "aws_access_key_id" not in captured
    assert "aws_secret_access_key" not in captured


def test_client_passes_endpoint_and_credentials_when_set(settings, monkeypatch):
    settings.OBJECT_STORAGE_ENDPOINT_URL = "http://minio:9000"
    settings.OBJECT_STORAGE_ACCESS_KEY = "minioadmin"
    settings.OBJECT_STORAGE_SECRET_KEY = "minioadmin"
    captured = {}

    def fake_client(service, **kwargs):
        captured.update(kwargs)
        return None

    monkeypatch.setattr(storage.boto3, "client", fake_client)

    storage._client()

    assert captured["endpoint_url"] == "http://minio:9000"
    assert captured["aws_access_key_id"] == "minioadmin"
    assert captured["aws_secret_access_key"] == "minioadmin"


def test_build_upload_key_is_unique_and_namespaced_by_brand_and_product_line():
    key1 = storage.build_upload_key("KILLER", "menswear", "april.xlsx")
    key2 = storage.build_upload_key("KILLER", "menswear", "april.xlsx")

    assert key1 != key2  # never overwrites -- every upload is immutable
    assert key1.startswith("uploads/killer/menswear/")
    assert key1.endswith("_april.xlsx")


def test_put_and_get_roundtrip_against_real_minio():
    key = storage.build_upload_key("KILLER", "menswear", "roundtrip-test.csv")
    content = b"NEW DATE,STORE CODE\n2023-04-01,ESIS170\n"

    storage.put(key, io.BytesIO(content), content_type="text/csv")
    body = storage.get(key).read()

    assert body == content


def test_presigned_url_is_reachable_and_returns_the_same_content():
    import urllib.request

    key = storage.build_upload_key("PEPE", "menswear", "presign-test.csv")
    content = b"DATE,STORE CODE\n2026-01-01,SI-032\n"
    storage.put(key, io.BytesIO(content), content_type="text/csv")

    url = storage.presigned_url(key, expires_in=60)

    with urllib.request.urlopen(url) as response:  # noqa: S310 - test-only, url is our own MinIO
        assert response.read() == content
