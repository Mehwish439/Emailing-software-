from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Custom user model. Keeps Django's username field for admin compatibility
    but authentication is done via email + password from the API.
    """

    email = models.EmailField(unique=True)
    company_name = models.CharField(max_length=255, blank=True)

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = ["email"]

    def __str__(self):
        return self.email or self.username
