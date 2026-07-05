from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

User = get_user_model()


class LoginView(TokenObtainPairView):
    """POST {email, password} -> {access, refresh}. Field name is 'email'
    because USERNAME_FIELD is 'email' on our custom User model."""

    permission_classes = [AllowAny]


class RefreshView(TokenRefreshView):
    permission_classes = [AllowAny]


class LogoutView(APIView):
    """Blacklists the given refresh token so it can no longer be used."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh = request.data.get("refresh")
        if not refresh:
            return Response({"detail": "refresh token is required"}, status=400)
        try:
            RefreshToken(refresh).blacklist()
        except TokenError:
            return Response({"detail": "invalid or already-blacklisted token"}, status=400)
        return Response(status=204)


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        return Response(
            {
                "email": user.email,
                "full_name": user.full_name,
                "is_staff": user.is_staff,
                "groups": list(user.groups.values_list("name", flat=True)),
                "permissions": sorted(user.get_all_permissions()),
            }
        )


class PasswordResetRequestView(APIView):
    """Stub: Phase 1 has no transactional email service, so this validates
    the request shape and generates a reset token but does not send
    anything yet. Always returns the same generic response regardless of
    whether the email is registered, so the endpoint can't be used to
    enumerate accounts.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get("email", "")
        user = User.objects.filter(email__iexact=email).first()
        if user is not None:
            # TODO: send via email once that service exists
            default_token_generator.make_token(user)
        return Response(
            {"detail": "If an account exists for this email, reset instructions have been sent."}
        )
