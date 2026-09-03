"""
Fixes a well-known DRF + SimpleJWT interaction: DRF's default exception
handler downgrades an authentication failure from 401 to 403 whenever the
authenticator doesn't provide a `WWW-Authenticate` challenge header —

    rest_framework/views.py, APIView.permission_denied():
        if request.authenticators and not request.successful_authenticator:
            raise exceptions.NotAuthenticated()   # -> would be 401...
        raise exceptions.PermissionDenied(...)     # ...but downstream:

    rest_framework/views.py, exception_handler():
        if isinstance(exc, (NotAuthenticated, AuthenticationFailed)):
            auth_header = get_authenticate_header(view, request)
            if not auth_header:
                exc.status_code = status.HTTP_403_FORBIDDEN  # <- silently swapped

`rest_framework_simplejwt.authentication.JWTAuthentication` never
implements `authenticate_header()`, so `get_authenticate_header()` always
returns falsy for it, and every missing/expired/invalid-token request comes
back as 403 instead of 401. This matters here specifically because the
frontend's axios interceptor (frontend/src/services/api.js) only attempts a
token refresh + redirect-to-login on a 401 — a 403 slips past it entirely,
which is exactly the "every endpoint fails with 403 at once" symptom this
was written to fix.
"""
from rest_framework_simplejwt.authentication import JWTAuthentication


class CustomJWTAuthentication(JWTAuthentication):
    def authenticate_header(self, request):
        return "Bearer"
