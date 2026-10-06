"""
Marketing Automation (rule-based).

Reuses what already exists instead of duplicating it:
  - ownership        -> `owner` FK to the project's User, same as ContactList/Tag/SignupForm
  - audience         -> contacts.Contact (+ Tag / ContactList / Segment for conditions)
  - email content    -> email_templates.EmailTemplate
  - sending          -> brevo.services.send_automation_email (same Brevo client/config)
  - suppression      -> contacts.Contact.status + contacts.Suppression
  - TimeStampedModel -> common.models

Status/choice VALUES are lowercase to match the rest of the codebase
(Campaign.Status, ScheduledCampaign.Status, Contact.Status ...).
"""
from django.conf import settings
from django.db import models
from django.db.models import Q

from common.models import TimeStampedModel
from contacts.models import Contact
from email_templates.models import EmailTemplate


class Automation(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        PAUSED = "paused", "Paused"
        COMPLETED = "completed", "Completed"

    class TriggerType(models.TextChoices):
        CONTACT_ADDED = "contact_added", "Contact added to a list"
        SIGNUP_FORM_SUBMITTED = "signup_form_submitted", "Signup form submitted"
        CART_ABANDONED = "cart_abandoned", "Cart abandoned (external event)"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="automations")
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    trigger_type = models.CharField(max_length=40, choices=TriggerType.choices)
    # CONTACT_ADDED          -> {"list_id": <ContactList id>}
    # SIGNUP_FORM_SUBMITTED  -> {"signup_form_id": <SignupForm id>}
    # CART_ABANDONED         -> {} (matched purely by event type)
    trigger_config = models.JSONField(default=dict, blank=True)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)

    # Blank = use the existing BREVO_SENDER_NAME / BREVO_SENDER_EMAIL settings.
    sender_name = models.CharField(max_length=255, blank=True)
    sender_email = models.EmailField(blank=True)

    # Delays are absolute durations computed from timezone-aware UTC "now", so
    # they are DST-safe. This zone is kept (validated with the same helper the
    # campaign scheduler uses) for DISPLAY of next-run times in the UI.
    timezone = models.CharField(max_length=64, default="Asia/Karachi")

    # False = a contact who already went through this automation (completed /
    # cancelled / failed) is never enrolled again by a trigger.
    allow_reenrollment = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]
        unique_together = ("owner", "name")
        indexes = [models.Index(fields=["owner", "status"]), models.Index(fields=["status", "trigger_type"])]

    def __str__(self):
        return self.name


class AutomationStep(TimeStampedModel):
    class ActionType(models.TextChoices):
        SEND_EMAIL = "send_email", "Send email"
        WAIT = "wait", "Wait"
        END_AUTOMATION = "end_automation", "End automation"

    class DelayUnit(models.TextChoices):
        MINUTES = "minutes", "Minutes"
        HOURS = "hours", "Hours"
        DAYS = "days", "Days"

    automation = models.ForeignKey(Automation, on_delete=models.CASCADE, related_name="steps")
    step_order = models.PositiveIntegerField()
    action_type = models.CharField(max_length=30, choices=ActionType.choices, default=ActionType.SEND_EMAIL)
    # PROTECT: a template in use by an automation can't be deleted from under it.
    email_template = models.ForeignKey(
        EmailTemplate, on_delete=models.PROTECT, null=True, blank=True, related_name="automation_steps"
    )
    # Delay BEFORE this step runs, measured from when the previous step finished
    # (or from enrollment for step 1). 0 = run immediately.
    delay_value = models.PositiveIntegerField(default=0)
    delay_unit = models.CharField(max_length=10, choices=DelayUnit.choices, default=DelayUnit.DAYS)
    # Extensible per-action settings, e.g.
    #   {"subject": "override subject"}
    #   {"condition": {"type": "has_tag", "tag_id": 3, "negate": false}}
    configuration = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["step_order"]
        unique_together = ("automation", "step_order")

    def __str__(self):
        return f"{self.automation_id}#{self.step_order} {self.action_type}"


class AutomationEnrollment(TimeStampedModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        PAUSED = "paused", "Paused"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    automation = models.ForeignKey(Automation, on_delete=models.CASCADE, related_name="enrollments")
    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name="automation_enrollments")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    # step_order of the NEXT step to run.
    current_step_order = models.PositiveIntegerField(default=1)
    started_at = models.DateTimeField()
    next_run_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    # Processing lease: set when a worker claims the row, cleared when done. A
    # lease older than AUTOMATION_LOCK_LEASE_SECONDS is considered abandoned
    # (worker died) and can be re-claimed.
    locked_at = models.DateTimeField(null=True, blank=True)
    # What caused the enrollment: "signup_form_submitted", "manual", ...
    source = models.CharField(max_length=40, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # At most ONE live enrollment per contact per automation.
            models.UniqueConstraint(
                fields=["automation", "contact"],
                condition=Q(status__in=["active", "paused"]),
                name="uniq_live_enrollment_per_contact",
            ),
        ]
        indexes = [models.Index(fields=["status", "next_run_at"])]

    def __str__(self):
        return f"{self.contact_id} in {self.automation_id} ({self.status})"


class AutomationExecution(TimeStampedModel):
    """One row per step ATTEMPT — doubles as the execution log."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Skipped"

    automation = models.ForeignKey(Automation, on_delete=models.CASCADE, related_name="executions")
    enrollment = models.ForeignKey(AutomationEnrollment, on_delete=models.CASCADE, related_name="executions")
    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name="automation_executions")
    step = models.ForeignKey(AutomationStep, on_delete=models.SET_NULL, null=True, blank=True, related_name="executions")
    step_order = models.PositiveIntegerField()
    action_type = models.CharField(max_length=30)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    attempt = models.PositiveIntegerField(default=1)
    executed_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    provider_message_id = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    # Filled from Brevo webhooks (brevo/webhooks.py -> automations.services.
    # handle_automation_webhook). Real data only; stays null until Brevo reports it.
    delivered_at = models.DateTimeField(null=True, blank=True)
    opened_at = models.DateTimeField(null=True, blank=True)
    clicked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            # Same step can never be attempted twice with the same attempt number.
            models.UniqueConstraint(fields=["enrollment", "step_order", "attempt"], name="uniq_execution_attempt"),
        ]
        indexes = [models.Index(fields=["automation", "status"])]

    def __str__(self):
        return f"{self.automation_id}/{self.contact_id} step {self.step_order} {self.status}"
