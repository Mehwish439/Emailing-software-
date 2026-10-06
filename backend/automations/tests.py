from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from brevo.webhooks import process_webhook_event
from campaigns.models import Campaign
from common.exceptions import BrevoAPIError
from contacts.models import Contact, ContactList, Suppression, Tag
from email_templates.models import EmailTemplate
from scheduling.models import ScheduledCampaign
from scheduling.services import process_due_schedules
from signup_forms.models import SignupForm

from .models import Automation, AutomationEnrollment, AutomationExecution, AutomationStep
from .services import (
    activate_automation, enroll_contact, pause_automation, process_due_automations, resume_automation,
)

User = get_user_model()
SEND = "brevo.client.BrevoClient.send_transactional_email"


class AutomationTestBase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="owner", email="owner@example.com", password="pass12345!")
        self.other = User.objects.create_user(username="other", email="other@example.com", password="pass12345!")
        self.client.force_authenticate(user=self.user)
        self.t1 = EmailTemplate.objects.create(name="Welcome", subject="Hi {{first_name}}", html_content="<p>Hello {{first_name}} {{unsubscribe_url}}</p>", created_by=self.user)
        self.t2 = EmailTemplate.objects.create(name="About", subject="About us", html_content="<p>About</p>", created_by=self.user)
        self.t3 = EmailTemplate.objects.create(name="Services", subject="Services", html_content="<p>Services</p>", created_by=self.user)
        self.other_template = EmailTemplate.objects.create(name="Theirs", subject="x", html_content="<p>x</p>", created_by=self.other)
        self.list = ContactList.objects.create(owner=self.user, name="Newsletter")
        self.form = SignupForm.objects.create(owner=self.user, name="Newsletter Signup", contact_list=self.list)
        self.contact = Contact.objects.create(owner=self.user, email="a@example.com", first_name="Ann")

    def make_automation(self, *, status_=Automation.Status.ACTIVE, trigger=Automation.TriggerType.SIGNUP_FORM_SUBMITTED, steps=None, name="Welcome Series", **kw):
        cfg = {"signup_form_id": self.form.id} if trigger == Automation.TriggerType.SIGNUP_FORM_SUBMITTED else (
            {"list_id": self.list.id} if trigger == Automation.TriggerType.CONTACT_ADDED else {})
        automation = Automation.objects.create(owner=self.user, name=name, trigger_type=trigger, trigger_config=cfg, status=status_, **kw)
        steps = steps or [(self.t1, 0, "days"), (self.t2, 2, "days"), (self.t3, 3, "days")]
        for i, (tpl, val, unit) in enumerate(steps, start=1):
            AutomationStep.objects.create(automation=automation, step_order=i, action_type="send_email", email_template=tpl, delay_value=val, delay_unit=unit)
        return automation

    def make_due(self, enrollment):
        AutomationEnrollment.objects.filter(pk=enrollment.pk).update(next_run_at=timezone.now() - timedelta(minutes=1))


class AutomationApiTests(AutomationTestBase):
    payload = lambda self: {  # noqa: E731
        "name": "Welcome New Subscribers", "description": "d",
        "trigger_type": "signup_form_submitted", "trigger_config": {"signup_form_id": self.form.id},
        "steps": [
            {"action_type": "send_email", "email_template": self.t1.id, "delay_value": 0, "delay_unit": "days"},
            {"action_type": "send_email", "email_template": self.t2.id, "delay_value": 2, "delay_unit": "days"},
        ],
    }

    def test_01_create_automation(self):
        r = self.client.post(reverse("automation-list"), self.payload(), format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["status"], "draft")
        self.assertEqual([s["step_order"] for s in r.data["steps"]], [1, 2])
        self.assertEqual(Automation.objects.get(pk=r.data["id"]).owner, self.user)

    def test_02_update_automation(self):
        a = self.client.post(reverse("automation-list"), self.payload(), format="json").data
        body = self.payload()
        body["name"] = "Renamed"
        body["steps"].append({"action_type": "send_email", "email_template": self.t3.id, "delay_value": 3, "delay_unit": "days"})
        r = self.client.put(reverse("automation-detail", args=[a["id"]]), body, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["name"], "Renamed")
        self.assertEqual(len(r.data["steps"]), 3)
        r = self.client.patch(reverse("automation-detail", args=[a["id"]]), {"description": "new"}, format="json")
        self.assertEqual(r.data["description"], "new")
        self.assertEqual(len(r.data["steps"]), 3)

    def test_03_activate_pause_resume(self):
        a = self.client.post(reverse("automation-list"), self.payload(), format="json").data
        r = self.client.post(reverse("automation-activate", args=[a["id"]]))
        self.assertEqual((r.status_code, r.data["status"]), (200, "active"))
        r = self.client.post(reverse("automation-pause", args=[a["id"]]))
        self.assertEqual(r.data["status"], "paused")
        r = self.client.post(reverse("automation-resume", args=[a["id"]]))
        self.assertEqual(r.data["status"], "active")
        # can't resume something that isn't paused / pause something that isn't active
        self.assertEqual(self.client.post(reverse("automation-resume", args=[a["id"]])).status_code, 400)

    def test_activate_requires_steps(self):
        body = self.payload(); body["steps"] = []
        a = self.client.post(reverse("automation-list"), body, format="json").data
        self.assertEqual(self.client.post(reverse("automation-activate", args=[a["id"]])).status_code, 400)

    def test_active_automation_workflow_locked(self):
        a = self.make_automation()
        r = self.client.patch(reverse("automation-detail", args=[a.id]), {"steps": []}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.client.patch(reverse("automation-detail", args=[a.id]), {"name": "Still editable"}, format="json")
        self.assertEqual(r.status_code, 200)

    def test_template_in_use_by_automation_cannot_be_deleted(self):
        self.make_automation()
        r = self.client.delete(reverse("template-detail", args=[self.t1.id]))
        self.assertEqual(r.status_code, 409, r.data)
        self.assertTrue(EmailTemplate.objects.filter(pk=self.t1.id).exists())

    def test_delete_automation(self):
        a = self.make_automation(status_="draft")
        self.assertEqual(self.client.delete(reverse("automation-detail", args=[a.id])).status_code, 204)

    def test_16_user_cannot_access_other_users_automation(self):
        theirs = Automation.objects.create(owner=self.other, name="Theirs", trigger_type="cart_abandoned")
        for name, method in [("automation-detail", "get"), ("automation-stats", "get"), ("automation-logs", "get"),
                             ("automation-enrollments", "get"), ("automation-activate", "post"), ("automation-pause", "post"),
                             ("automation-enroll", "post")]:
            r = getattr(self.client, method)(reverse(name, args=[theirs.id]), {"contact_id": self.contact.id}, format="json")
            self.assertEqual(r.status_code, 404, name)
        self.assertEqual(self.client.delete(reverse("automation-detail", args=[theirs.id])).status_code, 404)
        self.assertEqual(self.client.get(reverse("automation-list")).data["count"], 0)

    def test_cannot_attach_other_users_template_form_list_or_contact(self):
        body = self.payload(); body["steps"][0]["email_template"] = self.other_template.id
        self.assertEqual(self.client.post(reverse("automation-list"), body, format="json").status_code, 400)

        theirs_form = SignupForm.objects.create(owner=self.other, name="F")
        body = self.payload(); body["trigger_config"] = {"signup_form_id": theirs_form.id}
        self.assertEqual(self.client.post(reverse("automation-list"), body, format="json").status_code, 400)

        theirs_list = ContactList.objects.create(owner=self.other, name="L")
        body = self.payload(); body["trigger_type"] = "contact_added"; body["trigger_config"] = {"list_id": theirs_list.id}
        self.assertEqual(self.client.post(reverse("automation-list"), body, format="json").status_code, 400)

        a = self.make_automation()
        theirs_contact = Contact.objects.create(owner=self.other, email="x@example.com")
        r = self.client.post(reverse("automation-enroll", args=[a.id]), {"contact_id": theirs_contact.id}, format="json")
        self.assertEqual(r.data["enrolled"], 0)
        self.assertEqual(r.data["skipped"][0]["reason"], "not_found")

    def test_stats_logs_enrollments_endpoints(self):
        a = self.make_automation()
        with patch(SEND, return_value={"messageId": "<m1>"}):
            r = self.client.post(reverse("automation-enroll", args=[a.id]), {"contact_id": self.contact.id}, format="json")
        self.assertEqual(r.status_code, 201)
        stats = self.client.get(reverse("automation-stats", args=[a.id])).data
        self.assertEqual((stats["enrolled"], stats["active"], stats["emails_sent"], stats["emails_opened"]), (1, 1, 1, 0))
        self.assertEqual(self.client.get(reverse("automation-logs", args=[a.id])).data["count"], 1)
        self.assertEqual(self.client.get(reverse("automation-enrollments", args=[a.id])).data["count"], 1)
        listing = self.client.get(reverse("automation-list")).data["results"][0]
        self.assertEqual((listing["enrolled_count"], listing["emails_sent"]), (1, 1))


class AutomationEngineTests(AutomationTestBase):
    def test_06_07_08_signup_form_enrolls_and_runs_first_step(self):
        a = self.make_automation()
        url = reverse("signup-form-public-submit", args=[self.form.public_id])
        self.client.force_authenticate(user=None)
        with patch(SEND, return_value={"messageId": "<m1>"}) as send:
            with self.captureOnCommitCallbacks(execute=True):
                r = self.client.post(url, {"email": "new@example.com", "first_name": "Nia"}, format="json")
        self.assertEqual(r.status_code, 201)
        contact = Contact.objects.get(owner=self.user, email="new@example.com")
        self.assertIn(self.list, contact.lists.all())
        enrollment = AutomationEnrollment.objects.get(automation=a, contact=contact)       # 7. enrolled
        self.assertEqual(send.call_count, 1)                                                # 8. first step sent now
        self.assertEqual(send.call_args.kwargs["to"][0]["email"], "new@example.com")
        self.assertEqual(send.call_args.kwargs["subject"], "Hi Nia")
        self.assertIn("automation-%d" % a.id, send.call_args.kwargs["tags"])
        ex = AutomationExecution.objects.get(enrollment=enrollment)
        self.assertEqual((ex.status, ex.step_order, ex.provider_message_id), ("success", 1, "<m1>"))
        enrollment.refresh_from_db()
        self.assertEqual(enrollment.current_step_order, 2)
        self.assertEqual(enrollment.status, "active")

    def test_signup_form_with_other_form_or_paused_automation_does_not_enroll(self):
        self.make_automation(status_="paused")
        other_form = SignupForm.objects.create(owner=self.user, name="Other", contact_list=self.list)
        self.client.force_authenticate(user=None)
        with patch(SEND) as send:
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(reverse("signup-form-public-submit", args=[other_form.public_id]), {"email": "n@example.com"}, format="json")
        self.assertEqual(AutomationEnrollment.objects.count(), 0)
        send.assert_not_called()

    def test_09_10_delay_calculated_and_next_step_scheduled(self):
        a = self.make_automation()
        e = enroll_contact(a, self.contact)["enrollment"]
        self.assertAlmostEqual((e.next_run_at - e.started_at).total_seconds(), 0, delta=2)   # step 1 delay 0
        with patch(SEND, return_value={"messageId": "m"}):
            process_due_automations()
            e.refresh_from_db()
            executed = AutomationExecution.objects.get(enrollment=e, step_order=1).executed_at
            self.assertEqual(e.current_step_order, 2)
            self.assertAlmostEqual((e.next_run_at - executed).total_seconds(), 2 * 86400, delta=5)  # 2 days
            self.make_due(e)
            process_due_automations()
            e.refresh_from_db()
            executed = AutomationExecution.objects.get(enrollment=e, step_order=2).executed_at
            self.assertAlmostEqual((e.next_run_at - executed).total_seconds(), 3 * 86400, delta=5)  # 3 days

    def test_delay_units(self):
        a = self.make_automation(steps=[(self.t1, 0, "days"), (self.t2, 30, "minutes"), (self.t3, 5, "hours")])
        e = enroll_contact(a, self.contact)["enrollment"]
        with patch(SEND, return_value={}):
            process_due_automations()
            e.refresh_from_db(); self.assertAlmostEqual((e.next_run_at - timezone.now()).total_seconds(), 1800, delta=5)
            self.make_due(e); process_due_automations()
            e.refresh_from_db(); self.assertAlmostEqual((e.next_run_at - timezone.now()).total_seconds(), 5 * 3600, delta=5)

    def test_11_12_due_processed_and_completed(self):
        a = self.make_automation()
        e = enroll_contact(a, self.contact)["enrollment"]
        with patch(SEND, return_value={"messageId": "m"}) as send:
            process_due_automations()                 # step 1 (due now)
            self.assertEqual(send.call_count, 1)
            self.assertEqual(process_due_automations()["processed"], 0)   # step 2 not due yet
            self.make_due(e); process_due_automations()                   # step 2
            self.make_due(e); summary = process_due_automations()         # step 3 -> done
            self.assertEqual(summary["completed"], 1)
        e.refresh_from_db()
        self.assertEqual(send.call_count, 3)
        self.assertEqual((e.status, e.next_run_at is None, e.completed_at is not None), ("completed", True, True))
        self.assertEqual(AutomationExecution.objects.filter(enrollment=e, status="success").count(), 3)

    def test_wait_and_end_steps(self):
        a = Automation.objects.create(owner=self.user, name="W", trigger_type="cart_abandoned", status="active")
        AutomationStep.objects.create(automation=a, step_order=1, action_type="wait", delay_value=2, delay_unit="hours")
        AutomationStep.objects.create(automation=a, step_order=2, action_type="send_email", email_template=self.t1, delay_value=0)
        AutomationStep.objects.create(automation=a, step_order=3, action_type="end_automation", delay_value=0)
        AutomationStep.objects.create(automation=a, step_order=4, action_type="send_email", email_template=self.t2, delay_value=0)
        e = enroll_contact(a, self.contact)["enrollment"]
        self.assertAlmostEqual((e.next_run_at - timezone.now()).total_seconds(), 7200, delta=5)
        with patch(SEND, return_value={}) as send:
            self.make_due(e); process_due_automations()      # wait -> then email is immediately due in same run
            e.refresh_from_db()
        self.assertEqual(send.call_count, 1)
        self.assertEqual(e.status, "completed")              # END_AUTOMATION stopped before step 4

    def test_13_unsubscribed_contact_not_emailed(self):
        a = self.make_automation()
        e = enroll_contact(a, self.contact)["enrollment"]
        Contact.objects.filter(pk=self.contact.pk).update(status="unsubscribed")
        with patch(SEND) as send:
            summary = process_due_automations()
        send.assert_not_called()
        e.refresh_from_db()
        self.assertEqual(e.status, "cancelled")
        self.assertEqual(summary["cancelled"], 1)
        self.assertEqual(AutomationExecution.objects.get(enrollment=e).status, "skipped")

    def test_suppressed_email_not_emailed_or_enrolled(self):
        Suppression.objects.create(email="a@example.com", reason="hard_bounce")
        a = self.make_automation()
        self.assertFalse(enroll_contact(a, self.contact)["created"])
        c2 = Contact.objects.create(owner=self.user, email="b@example.com")
        e = enroll_contact(a, c2)["enrollment"]
        Suppression.objects.create(email="b@example.com", reason="spam_complaint")   # suppressed AFTER enrolling
        with patch(SEND) as send:
            process_due_automations()
        send.assert_not_called()
        e.refresh_from_db(); self.assertEqual(e.status, "cancelled")

    @override_settings(AUTOMATION_MAX_STEP_ATTEMPTS=2)
    def test_14_failed_email_creates_error_log_and_retries(self):
        a = self.make_automation()
        e = enroll_contact(a, self.contact)["enrollment"]
        with patch(SEND, side_effect=BrevoAPIError("Brevo down", status_code=503)):
            summary = process_due_automations()
        self.assertEqual(summary["failed"], 1)
        ex = AutomationExecution.objects.get(enrollment=e, attempt=1)
        self.assertEqual(ex.status, "failed")
        self.assertIn("Brevo down", ex.error_message)
        e.refresh_from_db()
        self.assertEqual((e.status, e.current_step_order), ("active", 1))           # not silently advanced
        self.assertGreater(e.next_run_at, timezone.now())                            # retry scheduled
        self.assertIn("Brevo down", e.last_error)
        # retry succeeds -> success logged as attempt 2, moves on
        self.make_due(e)
        with patch(SEND, return_value={"messageId": "ok"}):
            process_due_automations()
        e.refresh_from_db()
        self.assertEqual(AutomationExecution.objects.get(enrollment=e, attempt=2).status, "success")
        self.assertEqual(e.current_step_order, 2)

    @override_settings(AUTOMATION_MAX_STEP_ATTEMPTS=2)
    def test_enrollment_fails_after_max_attempts_and_non_retryable_fails_fast(self):
        a = self.make_automation()
        e = enroll_contact(a, self.contact)["enrollment"]
        with patch(SEND, side_effect=BrevoAPIError("boom", status_code=500)):
            process_due_automations(); self.make_due(e); process_due_automations()
        e.refresh_from_db(); self.assertEqual(e.status, "failed")
        c2 = Contact.objects.create(owner=self.user, email="bad@example.com")
        e2 = enroll_contact(a, c2)["enrollment"]
        with patch(SEND, side_effect=BrevoAPIError("invalid email", status_code=400)):
            process_due_automations()
        e2.refresh_from_db(); self.assertEqual(e2.status, "failed")   # 400 isn't retryable

    def test_one_failure_does_not_stop_other_contacts(self):
        a = self.make_automation()
        cb = Contact.objects.create(owner=self.user, email="b@example.com")
        cc = Contact.objects.create(owner=self.user, email="c@example.com")
        for c in (self.contact, cb, cc):
            enroll_contact(a, c)

        def fake(**kwargs):
            if kwargs["to"][0]["email"] == "b@example.com":
                raise BrevoAPIError("rejected", status_code=400)
            return {"messageId": "m"}

        with patch(SEND, side_effect=fake):
            summary = process_due_automations()
        self.assertEqual((summary["processed"], summary["sent"], summary["failed"]), (3, 2, 1))
        self.assertEqual(AutomationExecution.objects.filter(status="success").count(), 2)

    def test_15_rerunning_scheduler_does_not_duplicate_email(self):
        a = self.make_automation()
        enroll_contact(a, self.contact)
        with patch(SEND, return_value={"messageId": "m"}) as send:
            process_due_automations(); process_due_automations(); process_due_automations()
        self.assertEqual(send.call_count, 1)
        self.assertEqual(AutomationExecution.objects.count(), 1)

    def test_15b_leased_enrollment_is_not_claimed_twice_and_crashed_worker_never_double_sends(self):
        a = self.make_automation()
        e = enroll_contact(a, self.contact)["enrollment"]
        AutomationEnrollment.objects.filter(pk=e.pk).update(locked_at=timezone.now())   # another worker holds it
        with patch(SEND) as send:
            self.assertEqual(process_due_automations()["processed"], 0)
        send.assert_not_called()
        # worker died mid-send: lease expired + a PROCESSING execution was left behind
        AutomationEnrollment.objects.filter(pk=e.pk).update(locked_at=timezone.now() - timedelta(hours=1))
        AutomationExecution.objects.create(automation=a, enrollment=e, contact=self.contact, step_order=1,
                                           action_type="send_email", status="processing", attempt=1)
        with patch(SEND) as send:
            process_due_automations()
        send.assert_not_called()                                   # not re-sent
        e.refresh_from_db()
        self.assertEqual(e.current_step_order, 2)                  # but the automation moves on
        self.assertEqual(AutomationExecution.objects.get(enrollment=e, attempt=1).status, "failed")

    def test_no_duplicate_enrollment(self):
        a = self.make_automation()
        self.assertTrue(enroll_contact(a, self.contact)["created"])
        self.assertEqual(enroll_contact(a, self.contact)["reason"], "already_enrolled")
        self.assertEqual(AutomationEnrollment.objects.count(), 1)

    def test_reenrollment_rules(self):
        a = self.make_automation()
        e = enroll_contact(a, self.contact)["enrollment"]
        AutomationEnrollment.objects.filter(pk=e.pk).update(status="completed")
        self.assertEqual(enroll_contact(a, self.contact)["reason"], "already_went_through_automation")
        Automation.objects.filter(pk=a.pk).update(allow_reenrollment=True)
        a.refresh_from_db()
        self.assertTrue(enroll_contact(a, self.contact)["created"])

    def test_paused_automation_is_not_processed_and_resumes(self):
        a = self.make_automation()
        e = enroll_contact(a, self.contact)["enrollment"]
        pause_automation(a)
        with patch(SEND, return_value={}) as send:
            self.assertEqual(process_due_automations()["processed"], 0)
            send.assert_not_called()
            resume_automation(a)
            process_due_automations()
            self.assertEqual(send.call_count, 1)
        e.refresh_from_db(); self.assertEqual(e.current_step_order, 2)

    def test_condition_has_tag_skips_or_sends(self):
        vip = Tag.objects.create(owner=self.user, name="VIP")
        a = Automation.objects.create(owner=self.user, name="C", trigger_type="cart_abandoned", status="active")
        AutomationStep.objects.create(automation=a, step_order=1, action_type="send_email", email_template=self.t1,
                                      configuration={"condition": {"type": "has_tag", "tag_id": vip.id}})
        AutomationStep.objects.create(automation=a, step_order=2, action_type="send_email", email_template=self.t2,
                                      configuration={"condition": {"type": "has_tag", "tag_id": vip.id, "negate": True}})
        e = enroll_contact(a, self.contact)["enrollment"]
        with patch(SEND, return_value={}) as send:
            process_due_automations()
        subjects = [c.kwargs["subject"] for c in send.call_args_list]
        self.assertEqual(subjects, ["About us"])           # not VIP -> ELSE branch only
        self.assertEqual(AutomationExecution.objects.filter(enrollment=e, status="skipped").count(), 1)

    def test_contact_added_trigger_via_list(self):
        a = self.make_automation(trigger=Automation.TriggerType.CONTACT_ADDED, name="Added")
        c = Contact.objects.create(owner=self.user, email="list@example.com")
        with patch(SEND, return_value={}) as send:
            with self.captureOnCommitCallbacks(execute=True):
                c.lists.add(self.list)
                c.lists.add(self.list)         # re-adding an existing member must not re-trigger
        self.assertEqual(AutomationEnrollment.objects.filter(automation=a, contact=c).count(), 1)
        self.assertEqual(send.call_count, 1)

    def test_cart_abandoned_event_endpoint(self):
        a = Automation.objects.create(owner=self.user, name="Cart", trigger_type="cart_abandoned", status="active")
        AutomationStep.objects.create(automation=a, step_order=1, action_type="send_email", email_template=self.t1, delay_value=2, delay_unit="hours")
        r = self.client.post(reverse("automation-external-event"), {"event": "cart_abandoned", "email": "A@example.com"}, format="json")
        self.assertEqual((r.status_code, r.data["enrolled"]), (200, 1))
        e = AutomationEnrollment.objects.get(automation=a)
        self.assertAlmostEqual((e.next_run_at - timezone.now()).total_seconds(), 7200, delta=10)
        self.assertEqual(self.client.post(reverse("automation-external-event"), {"event": "nope", "email": "a@example.com"}, format="json").status_code, 400)
        self.assertEqual(self.client.post(reverse("automation-external-event"), {"event": "cart_abandoned", "email": "zzz@example.com"}, format="json").status_code, 404)

    def test_webhook_for_automation_email_updates_stats_and_suppresses(self):
        a = self.make_automation()
        e = enroll_contact(a, self.contact)["enrollment"]
        with patch(SEND, return_value={"messageId": "<m9>"}):
            process_due_automations()
        ex = AutomationExecution.objects.get(enrollment=e)
        payload = {"event": "opened", "email": "a@example.com", "message-id": "<m9>", "headers": {"X-Automation-Execution-Id": str(ex.id)}}
        self.assertEqual(process_webhook_event(payload), "processed-automation:opened")
        self.assertEqual(process_webhook_event(payload), "duplicate-ignored")
        ex.refresh_from_db(); self.assertIsNotNone(ex.opened_at)
        bounce = {"event": "hard_bounce", "email": "a@example.com", "message-id": "<m9>", "tags": [f"automation-exec-{ex.id}"]}
        process_webhook_event(bounce)
        self.assertTrue(Suppression.objects.filter(email="a@example.com").exists())
        e.refresh_from_db(); self.assertEqual(e.status, "cancelled")


class SchedulerIntegrationTests(AutomationTestBase):
    @override_settings(CRON_SECRET="s3cret")
    def test_process_due_endpoint_runs_automations_and_campaigns(self):
        a = self.make_automation()
        enroll_contact(a, self.contact)
        campaign = Campaign.objects.create(name="C", subject="S", sender_name="Me", sender_email="me@example.com", template=self.t1, created_by=self.user)
        campaign.contact_lists.add(self.list)
        self.contact.lists.add(self.list)
        ScheduledCampaign.objects.create(campaign=campaign, scheduled_at=timezone.now() - timedelta(minutes=1))
        campaign.status = Campaign.Status.SCHEDULED; campaign.save()
        self.client.force_authenticate(user=None)
        with patch(SEND, return_value={"messageId": "m"}) as send:
            r = self.client.post(reverse("scheduling-process-due"), HTTP_X_CRON_SECRET="s3cret")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["automations"]["sent"], 1)
        self.assertGreaterEqual(r.data["processed"], 1)             # campaign result shape unchanged
        self.assertGreaterEqual(send.call_count, 2)                 # 1 automation email + campaign recipient
        self.assertEqual(self.client.post(reverse("scheduling-process-due")).status_code, 401)

    @override_settings(CRON_SECRET="s3cret")
    def test_automation_crash_does_not_break_campaign_processing(self):
        self.client.force_authenticate(user=None)
        with patch("automations.services.process_due_automations", side_effect=RuntimeError("boom")):
            r = self.client.post(reverse("scheduling-process-due"), HTTP_X_CRON_SECRET="s3cret")
        self.assertEqual(r.status_code, 200)
        self.assertIn("error", r.data["automations"])

    def test_process_due_schedules_return_shape_unchanged(self):
        self.assertEqual(process_due_schedules(), [])
