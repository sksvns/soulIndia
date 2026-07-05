import io

from apps.ingestion import storage


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
