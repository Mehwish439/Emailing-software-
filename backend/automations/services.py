"""
Marketing Automation engine — plain Django/Python, no AI.

Flow
----
  trigger (signup form / list add / external event)
      -> enroll_contact()            creates an AutomationEnrollment, next_run_at = now + step-1 delay
      -> run first step now          (only if its delay is 0; otherwise the scheduler does it)
  cron -> POST /api/scheduling/process-due/
      -> scheduling.services.process_due_automation_steps()
      -> process_due_automations()   claims due enrollments one at a time, runs ONE step each,
                                     then sets next_run_at for the following step (or completes)

Safety
------
* Claiming is atomic (SELECT ... FOR UPDATE SKIP LOCKED where supported, same helper the campaign
  scheduler uses) and sets a lease (`locked_at`), so overlapping cron calls never process the same
  enrollment twice.
* Every attempt is a row in AutomationExecution with a unique (enrollment, step_order, attempt).
  A step that already has a SUCCESS/SKIPPED execution is never re-run, and an execution left
  PROCESSING by a crashed worker is NOT re-sent (at-most-once for emails) — it is marked FAILED and
  the enrollment moves on.
* One failing contact never stops the run: each enrollment is processed inside its own try/except.
* Suppression is re-checked immediately before every send (Contact.status + contacts.Suppression).
"""
import logging
import time
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.utils import timezone as dj_timezone

from common.db import select_for_update_kwargs
from common.exceptions import BrevoAPIError, ValidationAppError
from contacts.models import Contact, Segment, Tag
from contacts.services_suppression import is_suppressed

from .models import Automation, AutomationEnrollment, AutomationExecution, AutomationStep

logger = logging.getLogger(__name__)

LIVE_ENROLLMENT_STATUSES = (AutomationEnrollment.Status.ACTIVE, AutomationEnrollment.Status.PAUSED)


def _setting(name, default):
    return getattr(settings, name, default)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def delay_to_timedelta(value, unit):
    value = int(value or 0)
    if unit == AutomationStep.DelayUnit.MINUTES:
        return timedelta(minutes=value)
    if unit == AutomationStep.DelayUnit.HOURS:
        return timedelta(hours=value)
    return timedelta(days=value)


def step_delay(step):
    return delay_to_timedelta(step.delay_value, step.delay_unit)


def is_contact_sendable(contact):
    """(ok, reason). Reuses Contact.status + the global Suppression list."""
    if contact.status != Contact.Status.ACTIVE:
        return False, f"contact status is '{contact.status}'"
    if is_suppressed(contact.email):
        return False, "email is on the suppression list"
    return True, ""


def evaluate_condition(contact, condition):
    """
    Basic, reusable condition check (kept deliberately small):
        {"type": "has_tag",    "tag_id": 1,     "negate": false}
        {"type": "in_list",    "list_id": 2,    "negate": false}
        {"type": "in_segment", "segment_id": 3, "negate": false}
    No/empty condition -> True. Unknown type -> True (never silently blocks a send).
    """
    if not condition:
        return True
    ctype = condition.get("type")
    if ctype == "has_tag":
        result = contact.tags.filter(id=condition.get("tag_id")).exists()
    elif ctype == "in_list":
        result = contact.lists.filter(id=condition.get("list_id")).exists()
    elif ctype == "in_segment":
        segment = Segment.objects.filter(id=condition.get("segment_id"), owner_id=contact.owner_id).first()
        result = bool(segment) and segment.matching_contacts_queryset().filter(id=contact.id).exists()
    else:
        return True
    return (not result) if condition.get("negate") else result


# ---------------------------------------------------------------------------
# Validation / lifecycle
# ---------------------------------------------------------------------------

def validate_automation_ready(automation):
    """Raises ValidationAppError if the automation can't safely be (re)activated."""
    steps = list(automation.steps.select_related("email_template").order_by("step_order"))
    if not steps:
        raise ValidationAppError("Add at least one step before activating this automation.")
    for step in steps:
        if step.action_type == AutomationStep.ActionType.SEND_EMAIL:
            if step.email_template_id is None:
                raise ValidationAppError(f"Step {step.step_order}: choose an email template.")
            if step.email_template.created_by_id != automation.owner_id:
                raise ValidationAppError(f"Step {step.step_order}: template does not belong to your account.")
        if step.action_type == AutomationStep.ActionType.WAIT and step.delay_value <= 0:
            raise ValidationAppError(f"Step {step.step_order}: a Wait step needs a delay greater than 0.")
    cfg = automation.trigger_config or {}
    if automation.trigger_type == Automation.TriggerType.SIGNUP_FORM_SUBMITTED and not cfg.get("signup_form_id"):
        raise ValidationAppError("Choose the signup form that triggers this automation.")
    if automation.trigger_type == Automation.TriggerType.CONTACT_ADDED and not cfg.get("list_id"):
        raise ValidationAppError("Choose the list that triggers this automation.")


def activate_automation(automation):
    if automation.status == Automation.Status.ACTIVE:
        raise ValidationAppError("Automation is already active.")
    validate_automation_ready(automation)
    automation.status = Automation.Status.ACTIVE
    automation.save(update_fields=["status", "updated_at"])
    return automation


@transaction.atomic
def pause_automation(automation):
    if automation.status != Automation.Status.ACTIVE:
        raise ValidationAppError("Only an active automation can be paused.")
    automation.status = Automation.Status.PAUSED
    automation.save(update_fields=["status", "updated_at"])
    automation.enrollments.filter(status=AutomationEnrollment.Status.ACTIVE).update(
        status=AutomationEnrollment.Status.PAUSED, updated_at=dj_timezone.now()
    )
    return automation


@transaction.atomic
def resume_automation(automation):
    if automation.status != Automation.Status.PAUSED:
        raise ValidationAppError("Only a paused automation can be resumed.")
    validate_automation_ready(automation)
    automation.status = Automation.Status.ACTIVE
    automation.save(update_fields=["status", "updated_at"])
    # Anything that came due while paused simply runs on the next scheduler tick.
    automation.enrollments.filter(status=AutomationEnrollment.Status.PAUSED).update(
        status=AutomationEnrollment.Status.ACTIVE, updated_at=dj_timezone.now()
    )
    return automation


# ---------------------------------------------------------------------------
# Enrollment
# ---------------------------------------------------------------------------

def enroll_contact(automation, contact, *, source="manual"):
    """
    Enrolls `contact` into `automation`. Returns a dict:
        {"enrollment": <obj or None>, "created": bool, "reason": str}
    Never raises for the normal "can't enroll" cases (already enrolled, suppressed, ...) — those are
    reported via `reason` so triggers/bulk enrolls can carry on. Raises ValidationAppError only for
    misuse (wrong owner, automation not active, no steps).
    """
    if automation.status != Automation.Status.ACTIVE:
        raise ValidationAppError("Contacts can only be enrolled into an active automation.")
    if contact.owner_id != automation.owner_id:
        raise ValidationAppError("Contact does not belong to this automation's account.")

    ok, reason = is_contact_sendable(contact)
    if not ok:
        return {"enrollment": None, "created": False, "reason": f"not_sendable: {reason}"}

    existing = AutomationEnrollment.objects.filter(automation=automation, contact=contact)
    live = existing.filter(status__in=LIVE_ENROLLMENT_STATUSES).first()
    if live is not None:
        return {"enrollment": live, "created": False, "reason": "already_enrolled"}
    if existing.exists() and not automation.allow_reenrollment:
        return {"enrollment": None, "created": False, "reason": "already_went_through_automation"}

    first_step = automation.steps.order_by("step_order").first()
    if first_step is None:
        raise ValidationAppError("Automation has no steps.")

    now = dj_timezone.now()
    try:
        with transaction.atomic():
            enrollment = AutomationEnrollment.objects.create(
                automation=automation,
                contact=contact,
                status=AutomationEnrollment.Status.ACTIVE,
                current_step_order=first_step.step_order,
                started_at=now,
                next_run_at=now + step_delay(first_step),
                source=source,
            )
    except IntegrityError:
        # Lost a race with a concurrent enrollment of the same contact.
        return {"enrollment": None, "created": False, "reason": "already_enrolled"}
    return {"enrollment": enrollment, "created": True, "reason": "enrolled"}


def cancel_enrollments_for_email(email, reason):
    """Cancels every live enrollment for any contact with this email (used on suppression events)."""
    now = dj_timezone.now()
    return AutomationEnrollment.objects.filter(
        contact__email__iexact=email, status__in=LIVE_ENROLLMENT_STATUSES
    ).update(
        status=AutomationEnrollment.Status.CANCELLED, completed_at=now, last_error=reason[:2000],
        locked_at=None, updated_at=now,
    )


# ---------------------------------------------------------------------------
# Processing (called by the scheduler)
# ---------------------------------------------------------------------------

@transaction.atomic
def _claim_enrollment(enrollment_id=None):
    """
    Atomically finds, locks and leases ONE due enrollment (or the specific `enrollment_id` if it is
    due). Returns the enrollment or None. Mirrors scheduling.services._claim_next_due_schedule.
    """
    now = dj_timezone.now()
    lease = timedelta(seconds=_setting("AUTOMATION_LOCK_LEASE_SECONDS", 300))
    qs = (
        AutomationEnrollment.objects.select_for_update(**select_for_update_kwargs())
        .filter(
            status=AutomationEnrollment.Status.ACTIVE,
            next_run_at__lte=now,
            automation_id__in=Automation.objects.filter(status=Automation.Status.ACTIVE).values("id"),
        )
        .filter(Q(locked_at__isnull=True) | Q(locked_at__lt=now - lease))
        .order_by("next_run_at", "id")
    )
    if enrollment_id is not None:
        qs = qs.filter(id=enrollment_id)
    enrollment = qs.first()
    if enrollment is None:
        return None
    enrollment.locked_at = now
    enrollment.save(update_fields=["locked_at", "updated_at"])
    return enrollment


def _update_enrollment(enrollment, **fields):
    """
    Guarded write: only touches a still-live enrollment (so a concurrent cancel/delete is never
    overwritten) and always releases the lease.
    """
    fields.setdefault("locked_at", None)
    fields["updated_at"] = dj_timezone.now()
    return AutomationEnrollment.objects.filter(pk=enrollment.pk, status__in=LIVE_ENROLLMENT_STATUSES).update(**fields)


def _complete(enrollment, now):
    _update_enrollment(
        enrollment, status=AutomationEnrollment.Status.COMPLETED, completed_at=now, next_run_at=None, last_error=""
    )


def _advance(enrollment, automation, after_step, now):
    """Moves to the next step (scheduling next_run_at) or completes the enrollment."""
    nxt = None
    if after_step.action_type != AutomationStep.ActionType.END_AUTOMATION:
        nxt = automation.steps.filter(step_order__gt=after_step.step_order).order_by("step_order").first()
    if nxt is None:
        _complete(enrollment, now)
        return "completed"
    _update_enrollment(enrollment, current_step_order=nxt.step_order, next_run_at=now + step_delay(nxt), last_error="")
    return "scheduled_next"


def _is_retryable(exc):
    if isinstance(exc, BrevoAPIError):
        code = exc.status_code
        return code is None or code >= 500 or code in (408, 429)
    return not isinstance(exc, ValidationAppError)


def _send_step_email(automation, step, contact, execution):
    from campaigns.services import MAX_SEND_ATTEMPTS
    from brevo.services import send_automation_email

    template = step.email_template
    if template is None:
        raise ValidationAppError("Step has no email template.")
    if template.created_by_id != automation.owner_id:
        raise ValidationAppError("Step template does not belong to this account.")

    last_error = None
    for attempt in range(1, MAX_SEND_ATTEMPTS + 1):
        try:
            return send_automation_email(automation, step, execution, contact)
        except BrevoAPIError as exc:
            last_error = exc
            logger.warning(
                "Automation send failed automation=%s contact=%s step=%s (inline attempt %s/%s): %s",
                automation.id, contact.id, step.step_order, attempt, MAX_SEND_ATTEMPTS, exc,
            )
            if not _is_retryable(exc):
                break
    raise last_error


def _process_claimed_enrollment(enrollment):
    """Runs exactly one step of a claimed enrollment. Always releases the lease. Returns a result dict."""
    automation = enrollment.automation
    contact = enrollment.contact
    now = dj_timezone.now()
    result = {"enrollment_id": enrollment.id, "automation_id": automation.id, "contact_id": contact.id}

    step = automation.steps.filter(step_order=enrollment.current_step_order).select_related("email_template").first()
    if step is None:
        _complete(enrollment, now)
        return {**result, "result": "completed"}

    prior = list(enrollment.executions.filter(step_order=step.step_order))

    # 1. Never message a contact who is (now) unsubscribed / bounced / suppressed.
    ok, reason = is_contact_sendable(contact)
    if not ok:
        AutomationExecution.objects.create(
            automation=automation, enrollment=enrollment, contact=contact, step=step, step_order=step.step_order,
            action_type=step.action_type, status=AutomationExecution.Status.SKIPPED,
            attempt=max((e.attempt for e in prior), default=0) + 1,
            executed_at=now, error_message=f"Skipped: {reason}", metadata={"reason": "not_sendable"},
        )
        _update_enrollment(
            enrollment, status=AutomationEnrollment.Status.CANCELLED, completed_at=now, next_run_at=None,
            last_error=f"Cancelled: {reason}",
        )
        return {**result, "result": "cancelled", "detail": reason}

    # 2. Idempotency: look at what's already recorded for this step.
    if any(e.status in (AutomationExecution.Status.SUCCESS, AutomationExecution.Status.SKIPPED) for e in prior):
        outcome = _advance(enrollment, automation, step, now)  # already done — never run twice
        return {**result, "result": "already_done", "detail": outcome}
    if step.action_type == AutomationStep.ActionType.SEND_EMAIL:
        stale = [e for e in prior if e.status in (AutomationExecution.Status.PROCESSING, AutomationExecution.Status.PENDING)]
        if stale:
            # A previous worker died after (maybe) sending. Don't risk a duplicate email.
            for e in stale:
                e.status = AutomationExecution.Status.FAILED
                e.error_message = "Interrupted before the result was recorded; not re-sent to avoid a duplicate email."
                e.executed_at = now
                e.save(update_fields=["status", "error_message", "executed_at", "updated_at"])
            outcome = _advance(enrollment, automation, step, now)
            return {**result, "result": "interrupted_skipped", "detail": outcome}

    attempt = max((e.attempt for e in prior), default=0) + 1
    try:
        execution = AutomationExecution.objects.create(
            automation=automation, enrollment=enrollment, contact=contact, step=step, step_order=step.step_order,
            action_type=step.action_type, status=AutomationExecution.Status.PROCESSING, attempt=attempt,
            metadata={"template_id": step.email_template_id, "template_name": getattr(step.email_template, "name", "")},
        )
    except IntegrityError:
        _update_enrollment(enrollment)  # someone else owns this attempt; just release
        return {**result, "result": "duplicate_attempt_skipped"}

    # 3. Run the step.
    try:
        if not evaluate_condition(contact, (step.configuration or {}).get("condition")):
            execution.status = AutomationExecution.Status.SKIPPED
            execution.error_message = "Skipped: condition not met."
            execution.metadata = {**execution.metadata, "reason": "condition_not_met"}
            execution.executed_at = dj_timezone.now()
            execution.save()
            outcome = _advance(enrollment, automation, step, dj_timezone.now())
            return {**result, "result": "skipped", "detail": outcome}

        provider_id = ""
        if step.action_type == AutomationStep.ActionType.SEND_EMAIL:
            response = _send_step_email(automation, step, contact, execution)
            provider_id = str((response or {}).get("messageId") or "")[:255]
        # WAIT / END_AUTOMATION have no side effect — their effect is the delay / completion.

        finished = dj_timezone.now()
        with transaction.atomic():
            execution.status = AutomationExecution.Status.SUCCESS
            execution.provider_message_id = provider_id
            execution.executed_at = finished
            execution.error_message = ""
            execution.save()
            outcome = _advance(enrollment, automation, step, finished)
        return {**result, "result": "sent" if step.action_type == AutomationStep.ActionType.SEND_EMAIL else "ok", "detail": outcome}

    except Exception as exc:  # noqa: BLE001 - one contact must never abort the whole run
        message = str(exc)[:2000] or exc.__class__.__name__
        logger.warning(
            "Automation step failed automation=%s enrollment=%s step=%s attempt=%s: %s",
            automation.id, enrollment.id, step.step_order, attempt, message,
        )
        failed_at = dj_timezone.now()
        execution.status = AutomationExecution.Status.FAILED
        execution.error_message = message
        execution.executed_at = failed_at
        execution.save()

        max_attempts = _setting("AUTOMATION_MAX_STEP_ATTEMPTS", 3)
        if _is_retryable(exc) and attempt < max_attempts:
            delay = timedelta(minutes=_setting("AUTOMATION_RETRY_DELAY_MINUTES", 15) * attempt)
            _update_enrollment(enrollment, next_run_at=failed_at + delay, last_error=message)
            return {**result, "result": "failed_will_retry", "detail": message}
        _update_enrollment(
            enrollment, status=AutomationEnrollment.Status.FAILED, completed_at=failed_at, next_run_at=None,
            last_error=message,
        )
        return {**result, "result": "failed", "detail": message}


def run_enrollment_now(enrollment_id):
    """Claims and runs this enrollment's due step right away (used right after enrollment)."""
    enrollment = _claim_enrollment(enrollment_id)
    if enrollment is None:
        return None
    try:
        return _process_claimed_enrollment(enrollment)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected error running enrollment %s", enrollment_id)
        _update_enrollment(enrollment, last_error=str(exc)[:2000])
        return {"enrollment_id": enrollment_id, "result": "failed_unexpected", "detail": str(exc)[:500]}


def process_due_automations(limit=None, time_budget_seconds=None):
    """
    Processes due enrollments, one step each per claim, until nothing is due, `limit` steps have run
    or the time budget is spent (gunicorn has a 30s request timeout — leftovers just run on the next
    cron tick). Safe to call repeatedly/concurrently. Returns a summary dict.
    """
    limit = limit if limit is not None else _setting("AUTOMATION_BATCH_SIZE", 50)
    budget = time_budget_seconds if time_budget_seconds is not None else _setting("AUTOMATION_RUN_TIME_BUDGET_SECONDS", 20)
    started = time.monotonic()
    summary = {"processed": 0, "sent": 0, "failed": 0, "cancelled": 0, "completed": 0, "results": []}

    while summary["processed"] < limit and (time.monotonic() - started) < budget:
        enrollment = _claim_enrollment()
        if enrollment is None:
            break
        try:
            res = _process_claimed_enrollment(enrollment)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected error processing enrollment %s", enrollment.id)
            _update_enrollment(
                enrollment,
                next_run_at=dj_timezone.now() + timedelta(minutes=_setting("AUTOMATION_RETRY_DELAY_MINUTES", 15)),
                last_error=str(exc)[:2000],
            )
            res = {"enrollment_id": enrollment.id, "result": "failed_unexpected", "detail": str(exc)[:500]}
        summary["processed"] += 1
        r = res.get("result", "")
        if r == "sent":
            summary["sent"] += 1
        elif r.startswith("failed"):
            summary["failed"] += 1
        elif r == "cancelled":
            summary["cancelled"] += 1
        if res.get("detail") == "completed" or r == "completed":
            summary["completed"] += 1
        summary["results"].append(res)

    if summary["processed"]:
        logger.info(
            "process_due_automations: processed=%s sent=%s failed=%s cancelled=%s completed=%s",
            summary["processed"], summary["sent"], summary["failed"], summary["cancelled"], summary["completed"],
        )
    return summary


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def automation_stats(automation):
    enr = dict(automation.enrollments.values_list("status").annotate(c=Count("id")))
    E = AutomationEnrollment.Status
    emails = automation.executions.filter(action_type=AutomationStep.ActionType.SEND_EMAIL)
    sent = emails.filter(status=AutomationExecution.Status.SUCCESS)

    steps = []
    waiting = dict(
        automation.enrollments.filter(status__in=LIVE_ENROLLMENT_STATUSES)
        .values_list("current_step_order").annotate(c=Count("id"))
    )
    for step in automation.steps.select_related("email_template").order_by("step_order"):
        ex = automation.executions.filter(step_order=step.step_order)
        steps.append({
            "step_order": step.step_order,
            "action_type": step.action_type,
            "template_name": step.email_template.name if step.email_template_id else None,
            "success": ex.filter(status=AutomationExecution.Status.SUCCESS).count(),
            "failed": ex.filter(status=AutomationExecution.Status.FAILED).count(),
            "skipped": ex.filter(status=AutomationExecution.Status.SKIPPED).count(),
            "waiting": waiting.get(step.step_order, 0),
        })

    return {
        "enrolled": sum(enr.values()),
        "active": enr.get(E.ACTIVE, 0),
        "paused": enr.get(E.PAUSED, 0),
        "completed": enr.get(E.COMPLETED, 0),
        "failed": enr.get(E.FAILED, 0),
        "cancelled": enr.get(E.CANCELLED, 0),
        "emails_sent": sent.count(),
        "emails_failed": emails.filter(status=AutomationExecution.Status.FAILED).count(),
        "emails_skipped": emails.filter(status=AutomationExecution.Status.SKIPPED).count(),
        # Populated only from real Brevo webhook events (0 until Brevo reports them).
        "emails_delivered": sent.filter(delivered_at__isnull=False).count(),
        "emails_opened": sent.filter(opened_at__isnull=False).count(),
        "emails_clicked": sent.filter(clicked_at__isnull=False).count(),
        "steps": steps,
    }


# ---------------------------------------------------------------------------
# Brevo webhook hook (called from brevo/webhooks.py)
# ---------------------------------------------------------------------------

_SUPPRESSION_REASON = {
    "hard_bounce": "hard_bounce", "blocked": "blocked", "spam": "spam_complaint", "unsubscribed": "unsubscribed",
}


def _extract_execution_id(payload):
    import re

    headers = payload.get("headers") or {}
    value = headers.get("X-Automation-Execution-Id")
    if value:
        try:
            return int(value)
        except (TypeError, ValueError):
            pass
    for tag in payload.get("tags", []) or []:
        m = re.search(r"automation-exec-(\d+)", str(tag))
        if m:
            return int(m.group(1))
    return None


def handle_automation_webhook(payload, internal_event, email, timestamp):
    """
    Returns an outcome string if this webhook belongs to an automation email (handled here), or None
    if it isn't one (caller continues with the normal campaign path).
    """
    from contacts.services_suppression import add_suppression

    execution_id = _extract_execution_id(payload)
    if execution_id is None:
        return None
    execution = AutomationExecution.objects.filter(pk=execution_id).first()
    if execution is None:
        return "ignored-unknown-automation-execution"

    message_id = payload.get("message-id") or payload.get("messageId") or ""
    key = f"{message_id}:{internal_event}" if message_id else f"{email}:{internal_event}:{payload.get('date', '')}"
    seen = list((execution.metadata or {}).get("webhook_events", []))
    if key in seen:
        return "duplicate-ignored"
    seen.append(key)
    execution.metadata = {**(execution.metadata or {}), "webhook_events": seen[-50:]}

    if internal_event == "delivered" and not execution.delivered_at:
        execution.delivered_at = timestamp
    elif internal_event == "opened" and not execution.opened_at:
        execution.opened_at = timestamp
    elif internal_event == "clicked" and not execution.clicked_at:
        execution.clicked_at = timestamp
    execution.save()

    reason = _SUPPRESSION_REASON.get(internal_event)
    if reason:
        add_suppression(email, reason)
        cancel_enrollments_for_email(email, f"Cancelled: {reason.replace('_', ' ')} reported by Brevo")
    return f"processed-automation:{internal_event}"
