from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Custom user model. Keeps Django's username field for admin compatibility
    but authentication is done via email + password from the API.
    """

    email = models.EmailField(unique=True)
    company_name = models.CharField(max_length=255, blank=True)

    # --- Multi-tenant additions (all optional; legacy users keep working) ---
    class Role(models.TextChoices):
        USER = "user", "User"
        COMPANY_ADMIN = "company_admin", "Company admin"
        SUPER_ADMIN = "super_admin", "Platform super admin"

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.USER)
    company = models.ForeignKey(
        "tenancy.Company", null=True, blank=True, on_delete=models.SET_NULL, related_name="members"
    )
    # NULL = no per-user limit (legacy behaviour). Company admins set these.
    daily_quota = models.PositiveIntegerField(null=True, blank=True)
    monthly_quota = models.PositiveIntegerField(null=True, blank=True)

    @property
    def is_platform_admin(self):
        return self.is_superuser or self.role == self.Role.SUPER_ADMIN

    @property
    def is_company_admin(self):
        return self.company_id is not None and self.role == self.Role.COMPANY_ADMIN

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = ["email"]

    def __str__(self):
        return self.email or self.username
