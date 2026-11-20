from rest_framework.permissions import BasePermission


class IsCompanyAdmin(BasePermission):
    """Company admins of THEIR OWN company only. Platform admins use the /platform/ API."""

    message = "Company administrator access required."

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and u.is_active and u.is_company_admin)


class IsPlatformAdmin(BasePermission):
    message = "Platform administrator access required."

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and u.is_active and u.is_platform_admin)
