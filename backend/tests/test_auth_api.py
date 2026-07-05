import pytest
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_login_returns_access_and_refresh_tokens(data_inserter_user):
    client = APIClient()

    response = client.post(
        "/api/auth/login/",
        {"email": "inserter@example.com", "password": "StrongPass123"},
        format="json",
    )

    assert response.status_code == 200
    assert "access" in response.data
    assert "refresh" in response.data


@pytest.mark.django_db
def test_login_rejects_wrong_password(data_inserter_user):
    client = APIClient()

    response = client.post(
        "/api/auth/login/",
        {"email": "inserter@example.com", "password": "wrong-password"},
        format="json",
    )

    assert response.status_code == 401


@pytest.mark.django_db
def test_me_endpoint_requires_authentication():
    client = APIClient()

    response = client.get("/api/auth/me/")

    assert response.status_code == 401


@pytest.mark.django_db
def test_me_endpoint_returns_profile_and_permissions(data_inserter_user):
    client = APIClient()
    login = client.post(
        "/api/auth/login/",
        {"email": "inserter@example.com", "password": "StrongPass123"},
        format="json",
    )
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

    response = client.get("/api/auth/me/")

    assert response.status_code == 200
    assert response.data["email"] == "inserter@example.com"
    assert response.data["is_staff"] is False
    assert response.data["groups"] == ["Data Inserter"]
    assert "masterdata.view_dimbrand" in response.data["permissions"]
    assert "masterdata.add_dimbrand" not in response.data["permissions"]


@pytest.mark.django_db
def test_logout_blacklists_refresh_token(data_inserter_user):
    client = APIClient()
    login = client.post(
        "/api/auth/login/",
        {"email": "inserter@example.com", "password": "StrongPass123"},
        format="json",
    )
    access, refresh = login.data["access"], login.data["refresh"]
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

    logout_response = client.post("/api/auth/logout/", {"refresh": refresh}, format="json")
    assert logout_response.status_code == 204

    refresh_response = client.post("/api/auth/refresh/", {"refresh": refresh}, format="json")
    assert refresh_response.status_code == 401


@pytest.mark.django_db
def test_password_reset_stub_returns_generic_response_regardless_of_email(data_inserter_user):
    client = APIClient()

    for email in ("inserter@example.com", "nobody@example.com"):
        response = client.post("/api/auth/password-reset/", {"email": email}, format="json")
        assert response.status_code == 200
        assert response.data == {
            "detail": "If an account exists for this email, reset instructions have been sent."
        }
