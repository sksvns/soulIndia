import pytest


@pytest.mark.django_db
def test_health_endpoint_reports_ok(client):
    response = client.get("/health/")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["redis"] == "ok"
    assert body["broker"] == "ok"
