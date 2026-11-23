from django.db import migrations

# Providers that existed before SendPulse was added.
PREVIOUS = {"brevo", "smtp"}


def approve_sendpulse(apps, schema_editor):
    """
    A company with an explicit approved-provider list is restricted to exactly that list, and lists saved before
    SendPulse existed cannot mention it. A company approved for EVERY earlier provider was clearly not restricting
    anything, so it also gets SendPulse. Companies deliberately limited to fewer providers (e.g. Brevo only) are
    left alone, and companies with an empty list already get every provider. Only adds an item to a JSON list;
    nothing is removed or reset.
    """
    Company = apps.get_model("tenancy", "Company")
    for company in Company.objects.all():
        allowed = list(company.allowed_providers or [])
        if PREVIOUS.issubset(allowed) and "sendpulse" not in allowed:
            company.allowed_providers = allowed + ["sendpulse"]
            company.save(update_fields=["allowed_providers"])


class Migration(migrations.Migration):
    dependencies = [("tenancy", "0001_initial")]
    # Reverse is a no-op: we cannot know which entries were added by this step versus by an administrator.
    operations = [migrations.RunPython(approve_sendpulse, migrations.RunPython.noop)]
