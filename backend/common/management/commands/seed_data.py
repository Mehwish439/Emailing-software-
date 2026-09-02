from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from campaigns.models import Campaign
from contacts.models import Contact, ContactList
from email_templates.models import EmailTemplate

User = get_user_model()

DEMO_EMAIL = "admin@example.com"
DEMO_USERNAME = "admin"
DEMO_PASSWORD = "Admin@12345"


class Command(BaseCommand):
    help = "Seeds the database with a demo admin user, contacts, a list, a template, and a campaign."

    @transaction.atomic
    def handle(self, *args, **options):
        user, created = User.objects.get_or_create(
            username=DEMO_USERNAME,
            defaults={"email": DEMO_EMAIL, "is_staff": True, "is_superuser": True, "company_name": "Demo Co"},
        )
        if created:
            user.set_password(DEMO_PASSWORD)
            user.save()
            self.stdout.write(self.style.SUCCESS(f"Created demo admin user: {DEMO_USERNAME} / {DEMO_PASSWORD}"))
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
            f"Login with username='{DEMO_USERNAME}' password='{DEMO_PASSWORD}' (or email='{DEMO_EMAIL}')."
        ))
