from django.contrib.auth import get_user_model
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from .serializers import EmailTokenObtainPairSerializer, RegisterSerializer, UserSerializer

User = get_user_model()


class RegisterView(generics.CreateAPIView):
    """POST /api/auth/register/"""

    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    throttle_scope = "auth"

    def create(self, request, *args, **kwargs):
        from django.conf import settings

        if not settings.ALLOW_PUBLIC_REGISTRATION:
            return Response({"detail": "Public registration is disabled. Ask your administrator for an invitation."},
                            status=status.HTTP_403_FORBIDDEN)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "user": UserSerializer(user).data,
                "access": str(refresh.access_token),
                "refresh": str(refresh),
            },
            status=status.HTTP_201_CREATED,
        )


class LoginView(TokenObtainPairView):
    """POST /api/auth/login/"""

    serializer_class = EmailTokenObtainPairSerializer
    permission_classes = [AllowAny]
    throttle_scope = "auth"


class LogoutView(APIView):
    """POST /api/auth/logout/ -- blacklists the provided refresh token."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get("refresh")
        if not refresh_token:
            return Response({"detail": "Refresh token is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
        except TokenError:
            return Response({"detail": "Invalid or expired refresh token."}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"detail": "Successfully logged out."}, status=status.HTTP_205_RESET_CONTENT)


class MeView(generics.RetrieveUpdateAPIView):
    """GET/PATCH /api/auth/me/"""

    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user






class AcceptInviteView(APIView):
    """POST /api/auth/accept-invite/ {token, password} -- sets the first password for an invited user."""

    permission_classes = [AllowAny]
    throttle_scope = "auth"

    def post(self, request):
        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError as DjangoValidationError
        from django.core import signing

        from tenancy.services import read_invite_token

        invalid = Response({"detail": "This link is invalid, expired or has already been used."},
                           status=status.HTTP_400_BAD_REQUEST)
        try:
            uid, fingerprint = read_invite_token(request.data.get("token", ""))
            user = User.objects.get(pk=uid)
        except (signing.BadSignature, User.DoesNotExist, KeyError, TypeError):
            return invalid
        if user.password[-16:] != fingerprint:   # single-use: password changed since the link was issued
            return invalid
        claimed = (request.data.get("email") or "").strip().lower()
        if claimed and claimed != user.email.lower():
            return Response({"detail": "This invitation was issued for a different email address."},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            validate_password(request.data.get("password", ""), user)
        except DjangoValidationError as exc:
            return Response({"detail": list(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)
        user.set_password(request.data["password"])
        user.is_active = True
        # Names are cosmetic; role and company can NEVER be changed here - they were fixed by the inviter.
        for field in ("first_name", "last_name"):
            if str(request.data.get(field, "")).strip():
                setattr(user, field, str(request.data[field]).strip()[:150])
        user.save()
        return Response({"detail": "Password set. You can now sign in."})


class InviteInfoView(APIView):
    """GET /api/auth/invite-info/?token=... -> who/what the invitation is for (so the page can show it)."""

    permission_classes = [AllowAny]
    throttle_scope = "auth"

    def get(self, request):
        from django.core import signing

        from tenancy.services import read_invite_token

        bad = Response({"detail": "This link is invalid, expired or has already been used."}, status=400)
        try:
            uid, fingerprint = read_invite_token(request.query_params.get("token", ""))
            user = User.objects.select_related("company").get(pk=uid)
        except (signing.BadSignature, User.DoesNotExist, KeyError, TypeError):
            return bad
        if user.password[-16:] != fingerprint:
            return bad
        return Response({"email": user.email, "first_name": user.first_name, "last_name": user.last_name,
                         "role": user.role, "company": user.company.name if user.company_id else None,
                         "first_time": not user.has_usable_password()})


class RegisterCompanyView(APIView):
    """
    POST /api/auth/register-company/
    Creates a Company (on the limited trial plan) and its first Company Admin. The role is fixed on the
    server: nothing in the request can choose a role, a plan, a quota or a company id.
    """

    permission_classes = [AllowAny]
    throttle_scope = "auth"

    def post(self, request):
        from django.conf import settings
        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError as DjangoValidationError
        from django.db import transaction

        from tenancy.models import Company, Plan
        from tenancy.services import audit

        if not settings.ALLOW_COMPANY_SIGNUP:
            return Response({"detail": "Company sign-up is disabled. Contact the platform administrator."}, status=403)
        d = request.data
        name = " ".join(str(d.get("company_name", "")).split())
        email = str(d.get("email", "")).strip().lower()
        errors = {}
        if not (2 <= len(name) <= 255):
            errors["company_name"] = ["Enter your company name (2-255 characters)."]
        elif Company.objects.filter(name__iexact=name).exists():
            errors["company_name"] = ["A company with this name already exists. Ask its administrator for an invitation."]
        if not str(d.get("first_name", "")).strip():
            errors["first_name"] = ["Enter your name."]
        if "@" not in email or len(email) > 254:
            errors["email"] = ["Enter a valid work email address."]
        elif User.objects.filter(email__iexact=email).exists():
            errors["email"] = ["An account with this email already exists."]
        password = d.get("password", "")
        if password != d.get("password_confirm"):
            errors["password_confirm"] = ["Passwords do not match."]
        else:
            try:
                validate_password(password, User(username=email, email=email))
            except DjangoValidationError as exc:
                errors["password"] = list(exc.messages)
        if errors:
            return Response({"detail": errors}, status=400)

        plan, _ = Plan.objects.get_or_create(
            name=settings.TRIAL_PLAN_NAME,
            defaults={"price_monthly": 0, "max_users": settings.TRIAL_MAX_USERS, "daily_quota": settings.TRIAL_DAILY_QUOTA,
                      "monthly_quota": settings.TRIAL_MONTHLY_QUOTA, "analytics_level": "basic", "support_tier": "Community",
                      "scheduling": True, "custom_domains": 0},
        )
        if not plan.is_active:
            return Response({"detail": "Company sign-up is temporarily unavailable."}, status=503)

        with transaction.atomic():
            company = Company.objects.create(name=name, plan=plan, status=Company.Status.TRIAL)
            user = User(username=email, email=email, first_name=str(d["first_name"]).strip()[:150],
                        last_name=str(d.get("last_name", "")).strip()[:150], role=User.Role.COMPANY_ADMIN, company=company)
            user.set_password(password)
            user.save()
            audit(user, "company.registered", company=company, target=company, detail={"plan": plan.name, "self_service": True})
        refresh = RefreshToken.for_user(user)
        return Response({"user": UserSerializer(user).data, "access": str(refresh.access_token), "refresh": str(refresh)},
                        status=status.HTTP_201_CREATED)


class ForgotPasswordView(APIView):
    """
    POST /api/auth/forgot-password/ {email}
    Always answers 200 with the same message so it cannot be used to discover which emails have accounts.
    If the account exists and is active, a single-use 7-day link is emailed (when email sending is
    configured). The link is NEVER returned in the response.
    """

    permission_classes = [AllowAny]
    throttle_scope = "auth"

    def post(self, request):
        from tenancy.invites import send_link_email
        from tenancy.services import invite_url

        email = (request.data.get("email") or "").strip().lower()
        user = User.objects.filter(email__iexact=email, is_active=True).first() if "@" in email else None
        if user is not None:
            send_link_email(user, invite_url(user), kind="reset" if user.has_usable_password() else "invite")
        return Response({"detail": "If an account exists for that email, a reset link has been sent."})
