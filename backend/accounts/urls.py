from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import AcceptInviteView, ForgotPasswordView, InviteInfoView, RegisterCompanyView, LoginView, LogoutView, MeView, RegisterView

urlpatterns = [
    path("register/", RegisterView.as_view(), name="auth-register"),
    path("login/", LoginView.as_view(), name="auth-login"),
    path("refresh/", TokenRefreshView.as_view(), name="auth-refresh"),
    path("logout/", LogoutView.as_view(), name="auth-logout"),
    path("me/", MeView.as_view(), name="auth-me"),
    path("forgot-password/", ForgotPasswordView.as_view(), name="auth-forgot-password"),
    path("register-company/", RegisterCompanyView.as_view(), name="auth-register-company"),
    path("invite-info/", InviteInfoView.as_view(), name="auth-invite-info"),
    path("accept-invite/", AcceptInviteView.as_view(), name="auth-accept-invite"),
]
