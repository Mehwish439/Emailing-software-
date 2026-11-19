"""CORS + routing + auth regression tests for the browser (Vite on :5173) -> Django (:8000) setup."""
from django.conf import settings
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APITestCase

ORIGIN = "http://localhost:5173"
GOOD = {"company_name": "Cors Co", "first_name": "Cora", "email": "cora@cors.test",
        "password": "Str0ng-Pass-123!", "password_confirm": "Str0ng-Pass-123!"}


class CorsConfigTests(APITestCase):
    def test_settings_are_strict_and_not_wildcard(self):
        self.assertFalse(getattr(settings, "CORS_ALLOW_ALL_ORIGINS", False))
        self.assertIn(ORIGIN, settings.CORS_ALLOWED_ORIGINS)
        self.assertEqual(len(settings.CORS_ALLOWED_ORIGINS), len(set(settings.CORS_ALLOWED_ORIGINS)))
        self.assertTrue(all(not o.endswith("/") and o.startswith(("http://", "https://")) for o in settings.CORS_ALLOWED_ORIGINS))
        mw = settings.MIDDLEWARE
        self.assertLess(mw.index("corsheaders.middleware.CorsMiddleware"), mw.index("django.middleware.common.CommonMiddleware"))

    def test_preflight_for_register_company_and_me(self):
        for path, method in (("/api/auth/register-company/", "POST"), ("/api/auth/me/", "GET")):
            r = self.client.options(path, HTTP_ORIGIN=ORIGIN, HTTP_ACCESS_CONTROL_REQUEST_METHOD=method,
                                    HTTP_ACCESS_CONTROL_REQUEST_HEADERS="authorization,content-type")
            self.assertEqual(r.status_code, 200, path)
            self.assertEqual(r["Access-Control-Allow-Origin"], ORIGIN)
            self.assertIn("authorization", r["Access-Control-Allow-Headers"].lower())
            self.assertIn(method, r["Access-Control-Allow-Methods"])

    def test_errors_still_carry_cors_headers_so_the_browser_shows_the_real_status(self):
        r = self.client.get("/api/auth/me/", HTTP_ORIGIN=ORIGIN)              # unauthenticated
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r["Access-Control-Allow-Origin"], ORIGIN)
        r = self.client.get("/api/does-not-exist/", HTTP_ORIGIN=ORIGIN)       # genuine 404
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r["Access-Control-Allow-Origin"], ORIGIN)

    def test_other_origins_are_not_allowed(self):
        r = self.client.get("/api/auth/me/", HTTP_ORIGIN="https://evil.example")
        self.assertNotIn("Access-Control-Allow-Origin", r)
        r = self.client.options("/api/auth/register-company/", HTTP_ORIGIN="https://evil.example", HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST")
        self.assertNotIn("Access-Control-Allow-Origin", r)

    @override_settings(CORS_ALLOWED_ORIGINS=["https://app.example.com"])
    def test_production_style_list_replaces_dev_origin(self):
        self.assertNotIn("Access-Control-Allow-Origin", self.client.get("/api/auth/me/", HTTP_ORIGIN=ORIGIN))
        self.assertEqual(self.client.get("/api/auth/me/", HTTP_ORIGIN="https://app.example.com")["Access-Control-Allow-Origin"], "https://app.example.com")


class AuthRoutingFlowTests(APITestCase):
    def setUp(self):
        cache.clear()

    def test_company_registration_login_and_me_from_the_browser_origin(self):
        r = self.client.post("/api/auth/register-company/", GOOD, format="json", HTTP_ORIGIN=ORIGIN)
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r["Access-Control-Allow-Origin"], ORIGIN)
        self.assertEqual(r.data["user"]["role"], "company_admin")

        login = self.client.post("/api/auth/login/", {"username": "cora@cors.test", "password": GOOD["password"]}, format="json", HTTP_ORIGIN=ORIGIN)
        self.assertEqual(login.status_code, 200)
        self.assertEqual(login.data["user"]["role"], "company_admin")

        me = self.client.get("/api/auth/me/", HTTP_ORIGIN=ORIGIN, HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        self.assertEqual((me.status_code, me.data["email"], me["Access-Control-Allow-Origin"]), (200, "cora@cors.test", ORIGIN))

        refreshed = self.client.post("/api/auth/refresh/", {"refresh": login.data["refresh"]}, format="json", HTTP_ORIGIN=ORIGIN)
        self.assertEqual(refreshed.status_code, 200)
        self.assertIn("access", refreshed.data)

    def test_me_requires_a_valid_token(self):
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 401)
        self.assertEqual(self.client.get("/api/auth/me/", HTTP_AUTHORIZATION="Bearer garbage").status_code, 401)

    def test_a_stale_bearer_token_breaks_public_endpoints_which_is_why_the_frontend_no_longer_sends_it(self):
        r = self.client.post("/api/auth/register-company/", GOOD, format="json", HTTP_AUTHORIZATION="Bearer expired.or.garbage")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(self.client.post("/api/auth/register-company/", GOOD, format="json").status_code, 201)

    def test_every_documented_auth_route_exists(self):
        from django.urls import resolve

        for path in ("/api/auth/me/", "/api/auth/register-company/", "/api/auth/login/", "/api/auth/refresh/", "/api/auth/logout/",
                     "/api/auth/accept-invite/", "/api/auth/invite-info/", "/api/auth/forgot-password/"):
            self.assertTrue(resolve(path).view_name, path)
