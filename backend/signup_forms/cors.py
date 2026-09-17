# NEW FILE (Signup Forms feature)
"""
Allows cross-origin requests to this app's two PUBLIC signup-form endpoints
(public form detail + public form submission) from any origin, without
touching the site-wide CORS_ALLOWED_ORIGINS whitelist in config/settings.py.

Why not just add to CORS_ALLOWED_ORIGINS: that setting is a fixed list of
known origins (today just the app's own frontend). A signup form is meant
to be embedded on arbitrary external customer websites we can never
enumerate in advance, so the two public paths need "any origin" — but
every other endpoint (contacts, campaigns, auth, ...) must stay locked
down to the whitelist exactly as configured today.

django-cors-headers has a documented extension point for exactly this: a
receiver on `check_request_enabled` that opts a specific request in based
on its path. When it returns True for a request, CorsMiddleware reflects
that request's Origin back on both the preflight (OPTIONS) response and
the actual response — effectively "any origin" for just that request
(equivalent in practice to CORS_ALLOW_ALL_ORIGINS=True but scoped to these
two paths only). See corsheaders/middleware.py's is_enabled()/check_signal().
"""
from corsheaders.signals import check_request_enabled

_PUBLIC_PATH_PREFIX = "/api/public/signup-forms/"


def _allow_public_signup_form_requests(sender, request, **kwargs):
    return request.path_info.startswith(_PUBLIC_PATH_PREFIX)


check_request_enabled.connect(_allow_public_signup_form_requests)
