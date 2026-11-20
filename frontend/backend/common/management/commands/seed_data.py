import os
import secrets

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from campaigns.models import Campaign
from contacts.models import Contact, ContactList
from email_templates.models import EmailTemplate
from email_templates.starter_templates import STARTER_TEMPLATES

User = get_user_model()

DEMO_EMAIL = "admin@example.com"
DEMO_USERNAME = "admin"


class Command(BaseCommand):
    help = (
        "LOCAL DEVELOPMENT ONLY. Seeds a demo user, contacts, a list, a template and a campaign. "
        "Refuses to run when DEBUG is False. The demo password is taken from SEED_ADMIN_PASSWORD or randomly "
        "generated and shown once - there is no built-in password."
    )

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_data is for local development only and refuses to run when DEBUG is False.")
        DEMO_PASSWORD = os.getenv("SEED_ADMIN_PASSWORD") or secrets.token_urlsafe(14)
        user, created = User.objects.get_or_create(
            username=DEMO_USERNAME,
            defaults={"email": DEMO_EMAIL, "is_staff": True, "is_superuser": True, "company_name": "Demo Co"},
        )
        if created:
            user.set_password(DEMO_PASSWORD)
            user.save()
            self.stdout.write(self.style.SUCCESS(f"Created demo user \"{DEMO_USERNAME}\". Password (shown once): {DEMO_PASSWORD}"))
        else:
            self.stdout.write("Demo admin user already exists, skipping creation.")

        contact_list, _ = ContactList.objects.get_or_create(
            owner=user, name="Demo Subscribers", defaults={"description": "Seeded demo contact list"}
        )

        demo_contacts = [
            ("Ali", "Khan", "ali.khan@example.com"),
            ("Sara", "Ahmed", "sara.ahmed@example.com"),
            ("Bilal", "Hussain", "bilal.hussain@example.com"),
            ("Ayesha", "Malik", "ayesha.malik@example.com"),
            ("Usman", "Farooq", "usman.farooq@example.com"),
        ]
        created_contacts = 0
        for first, last, email in demo_contacts:
            contact, was_created = Contact.objects.get_or_create(
                owner=user, email=email, defaults={"first_name": first, "last_name": last}
            )
            contact.lists.add(contact_list)
            if was_created:
                created_contacts += 1

        template, _ = EmailTemplate.objects.get_or_create(
            created_by=user,
            name="Demo Welcome Template",
            defaults={
                "subject": "Welcome to our newsletter!",
                "html_content": (
                    "<h1>Welcome!</h1><p>Thanks for subscribing to our updates. "
                    "This is a demo email template seeded for local development.</p>"
                ),
            },
        )

        # Also seed the full starter-template library (see
        # email_templates/starter_templates.py) as real, editable templates
        # for the demo user — gives a fresh account something to look at
        # in the Templates list beyond just the one welcome template above.
        created_templates = 0
        for starter in STARTER_TEMPLATES:
            _, was_created = EmailTemplate.objects.get_or_create(
                created_by=user,
                name=starter["name"],
                defaults={"subject": starter["subject"], "html_content": starter["html_content"]},
            )
            if was_created:
                created_templates += 1

        campaign, _ = Campaign.objects.get_or_create(
            created_by=user,
            name="Demo Welcome Campaign",
            defaults={
                "subject": template.subject,
                "sender_name": "Demo Co",
                "sender_email": "no-reply@example.com",
                "template": template,
                "status": Campaign.Status.DRAFT,
            },
        )
        campaign.contact_lists.add(contact_list)

        self.stdout.write(self.style.SUCCESS(
            f"Seed complete. Contacts created this run: {created_contacts}. "
            f"Starter templates created this run: {created_templates}. "
            f"Login with username='{DEMO_USERNAME}' password='{DEMO_PASSWORD}' (or email='{DEMO_EMAIL}')."
        ))