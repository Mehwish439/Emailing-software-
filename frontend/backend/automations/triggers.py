"""
Trigger layer: turns "something happened to a contact" into enrollments.

Adding a new trigger later = add a TriggerType, call fire_trigger() from wherever the event happens
(see signup_forms/services.py, automations/signals.py and POST /api/automations/events/).
Triggers NEVER raise to their caller — a broken automation must not break signups or list edits.
"""
import logging

from django.conf import settings
from django.db import transaction

from contacts.models import Contact

from .models import Automation
from .services import enroll_contact, run_enrollment_now

logger = logging.getLogger(__name__)

# External event name -> trigger type (future Shopify/WooCommerce/webhook integrations post these).
EVENT_TO_TRIGGER = {
    "cart_abandoned": Automation.TriggerType.CART_ABANDONED,
}


def _matches(automation, trigger_type, match):
    cfg = automation.trigger_config or {}
    if trigger_type == Automation.TriggerType.SIGNUP_FORM_SUBMITTED:
        return str(cfg.get("signup_form_id")) == str(match.get("signup_form_id"))
    if trigger_type == Automation.TriggerType.CONTACT_ADDED:
        return str(cfg.get("list_id")) == str(match.get("list_id"))
    return True  # CART_ABANDONED etc.: matched by event type alone


def _run_first_steps(enrollment_ids):
    if not getattr(settings, "AUTOMATION_RUN_FIRST_STEP_INLINE", True):
        return  # the scheduler (cron) will pick them up
    for enrollment_id in enrollment_ids:
        try:
            run_enrollment_now(enrollment_id)  # only runs if the first step is already due (delay 0)
        except Exception:  # noqa: BLE001
            logger.exception("Immediate first-step run failed for enrollment %s (cron will retry)", enrollment_id)


def fire_trigger(owner, trigger_type, contact, *, match=None):
    """Enrolls `contact` into every ACTIVE automation of `owner` listening for this trigger."""
    match = match or {}
    enrollment_ids = []
    results = []
    try:
        with transaction.atomic():  # savepoint: a DB error here can't poison the caller's transaction
            candidates = Automation.objects.filter(
                owner=owner, status=Automation.Status.ACTIVE, trigger_type=trigger_type
            )
            for automation in candidates:
                if not _matches(automation, trigger_type, match):
                    continue
                res = enroll_contact(automation, contact, source=trigger_type)
                results.append({"automation_id": automation.id, **{k: v for k, v in res.items() if k != "enrollment"}})
                if res["created"]:
                    enrollment_ids.append(res["enrollment"].id)
    except Exception:  # noqa: BLE001
        logger.exception("fire_trigger failed trigger=%s contact=%s", trigger_type, getattr(contact, "id", None))
        return results

    if enrollment_ids:
        # After commit, so we never hold the signup's DB transaction open during a Brevo HTTP call.
        transaction.on_commit(lambda: _run_first_steps(enrollment_ids))
    return results


def handle_signup_form_submitted(contact, form):
    return fire_trigger(
        form.owner, Automation.TriggerType.SIGNUP_FORM_SUBMITTED, contact, match={"signup_form_id": form.id}
    )


def handle_contact_added_to_lists(contact, list_ids):
    results = []
    for list_id in list_ids:
        results += fire_trigger(
            contact.owner, Automation.TriggerType.CONTACT_ADDED, contact, match={"list_id": list_id}
        )
    return results


def handle_external_event(owner, event, contact):
    trigger_type = EVENT_TO_TRIGGER.get(event)
    if trigger_type is None:
        raise ValueError(f"Unsupported event '{event}'.")
    return fire_trigger(owner, trigger_type, contact)
