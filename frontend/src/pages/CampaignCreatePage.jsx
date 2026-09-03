import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import DateTimeTimezonePicker from "../components/DateTimeTimezonePicker";
import { useToast } from "../context/ToastContext";
import { createCampaign, sendCampaignNow, sendTestEmail } from "../services/campaignService";
import { listContactLists } from "../services/contactService";
import { createSchedule } from "../services/schedulingService";
import { listTemplates } from "../services/templateService";
import { localDateTimeInZoneToUTC } from "../utils/timezone";

const STEPS = ["Campaign Details", "Recipients", "Email Content", "Review", "Send or Schedule"];

function defaultDate() {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  return d.toISOString().split("T")[0];
}

export default function CampaignCreatePage() {
  const navigate = useNavigate();
  const { showToast } = useToast();

  const [step, setStep] = useState(0);
  const [templates, setTemplates] = useState([]);
  const [lists, setLists] = useState([]);

  const [form, setForm] = useState({
    name: "",
    subject: "",
    sender_name: "",
    sender_email: "",
    template: "",
    contact_lists: [],
  });

  const [sendChoice, setSendChoice] = useState("now"); // "now" | "schedule"
  const [scheduleValue, setScheduleValue] = useState({ date: defaultDate(), time: "10:00", timezone: "Asia/Karachi" });
  const [scheduleError, setScheduleError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    listTemplates({ page_size: 100 }).then((data) => setTemplates(data.results || []));
    listContactLists({ page_size: 100 }).then((data) => setLists(data.results || data || []));
  }, []);

  const selectedTemplate = templates.find((t) => String(t.id) === String(form.template));
  const selectedLists = lists.filter((l) => form.contact_lists.includes(l.id));
  const totalRecipients = selectedLists.reduce((sum, l) => sum + (l.contact_count || 0), 0);

  const toggleList = (id) => {
    setForm((prev) => ({
      ...prev,
      contact_lists: prev.contact_lists.includes(id)
        ? prev.contact_lists.filter((x) => x !== id)
        : [...prev.contact_lists, id],
    }));
  };

  const canProceed = () => {
    if (step === 0) return form.name && form.subject && form.sender_name && form.sender_email;
    if (step === 1) return form.contact_lists.length > 0;
    if (step === 2) return !!form.template;
    return true;
  };

  const handleNext = () => setStep((s) => Math.min(s + 1, STEPS.length - 1));
  const handleBack = () => setStep((s) => Math.max(s - 1, 0));

  const handleFinalSubmit = async () => {
    setSubmitting(true);
    setScheduleError("");
    try {
      const campaign = await createCampaign(form);

      if (sendChoice === "now") {
        await sendCampaignNow(campaign.id);
        showToast("Campaign is sending now!", "success");
      } else {
        const scheduledAtUTC = localDateTimeInZoneToUTC(scheduleValue.date, scheduleValue.time, scheduleValue.timezone);
        await createSchedule({
          campaign: campaign.id,
          scheduled_at: scheduledAtUTC,
          timezone: scheduleValue.timezone,
        });
        showToast("Campaign scheduled!", "success");
      }
      navigate(`/campaigns/${campaign.id}`);
    } catch (err) {
      const detail = err.response?.data?.detail || "Failed to create/send campaign.";
      setScheduleError(detail);
      showToast(detail, "error");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Create Campaign</h1>
        <p className="text-sm text-slate-500">Follow the steps to build and send your campaign.</p>
      </div>

      {/* Step indicator */}
      <div className="flex items-center gap-2 overflow-x-auto pb-2">
        {STEPS.map((label, idx) => (
          <div key={label} className="flex items-center gap-2 flex-shrink-0">
            <div
              className={`h-7 w-7 rounded-full flex items-center justify-center text-xs font-semibold ${
                idx === step
                  ? "bg-brand-600 text-white"
                  : idx < step
                  ? "bg-brand-100 text-brand-700"
                  : "bg-slate-100 text-slate-400"
              }`}
            >
              {idx + 1}
            </div>
            <span className={`text-xs font-medium ${idx === step ? "text-slate-900" : "text-slate-400"}`}>{label}</span>
            {idx < STEPS.length - 1 && <div className="w-6 h-px bg-slate-200" />}
          </div>
        ))}
      </div>

      <div className="card p-6">
        {step === 0 && (
          <div className="space-y-4">
            <div>
              <label className="label">Campaign name</label>
              <input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </div>
            <div>
              <label className="label">Subject line</label>
              <input className="input" value={form.subject} onChange={(e) => setForm({ ...form, subject: e.target.value })} />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label">Sender name</label>
                <input
                  className="input"
                  value={form.sender_name}
                  onChange={(e) => setForm({ ...form, sender_name: e.target.value })}
                />
              </div>
              <div>
                <label className="label">Sender email</label>
                <input
                  className="input"
                  type="email"
                  value={form.sender_email}
                  onChange={(e) => setForm({ ...form, sender_email: e.target.value })}
                />
              </div>
            </div>
          </div>
        )}

        {step === 1 && (
          <div className="space-y-3">
            <p className="text-sm text-slate-600">Select which contact lists should receive this campaign.</p>
            {lists.length === 0 ? (
              <p className="text-sm text-slate-500">No contact lists found. Create one first from the Contacts page.</p>
            ) : (
              <div className="space-y-2">
                {lists.map((l) => (
                  <label
                    key={l.id}
                    className="flex items-center justify-between rounded-lg border border-slate-200 px-4 py-3 cursor-pointer hover:bg-slate-50"
                  >
                    <div className="flex items-center gap-3">
                      <input type="checkbox" checked={form.contact_lists.includes(l.id)} onChange={() => toggleList(l.id)} />
                      <span className="text-sm font-medium text-slate-900">{l.name}</span>
                    </div>
                    <span className="text-xs text-slate-500">{l.contact_count} contacts</span>
                  </label>
                ))}
              </div>
            )}
            {totalRecipients > 0 && (
              <p className="text-sm text-slate-600">
                Estimated recipients: <span className="font-semibold">{totalRecipients}</span>
              </p>
            )}
          </div>
        )}

        {step === 2 && (
          <div className="space-y-3">
            <p className="text-sm text-slate-600">Choose the email template for this campaign.</p>
            {templates.length === 0 ? (
              <p className="text-sm text-slate-500">No templates found. Create one first from the Templates page.</p>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {templates.map((t) => (
                  <label
                    key={t.id}
                    className={`rounded-lg border px-4 py-3 cursor-pointer ${
                      String(form.template) === String(t.id) ? "border-brand-500 ring-1 ring-brand-500" : "border-slate-200"
                    }`}
                  >
                    <input
                      type="radio"
                      name="template"
                      className="sr-only"
                      checked={String(form.template) === String(t.id)}
                      onChange={() => setForm({ ...form, template: t.id })}
                    />
                    <p className="text-sm font-medium text-slate-900">{t.name}</p>
                    <p className="text-xs text-slate-500">{t.subject}</p>
                  </label>
                ))}
              </div>
            )}
          </div>
        )}

        {step === 3 && (
          <div className="space-y-4">
            <dl className="divide-y divide-slate-100 text-sm">
              <Row label="Campaign Name" value={form.name} />
              <Row label="Subject" value={form.subject} />
              <Row label="Sender" value={`${form.sender_name} <${form.sender_email}>`} />
              <Row label="Template" value={selectedTemplate?.name || "—"} />
              <Row label="Recipients" value={`${selectedLists.map((l) => l.name).join(", ") || "—"} (${totalRecipients} contacts)`} />
            </dl>
            {selectedTemplate && (
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
                <p className="text-xs text-slate-400 mb-2">Content preview</p>
                <div
                  className="bg-white rounded-lg p-4"
                  dangerouslySetInnerHTML={{ __html: selectedTemplate.html_content }}
                />
              </div>
            )}
          </div>
        )}

        {step === 4 && (
          <div className="space-y-5">
            <div className="flex gap-3">
              <label
                className={`flex-1 rounded-lg border px-4 py-3 cursor-pointer text-center text-sm font-medium ${
                  sendChoice === "now" ? "border-brand-500 bg-brand-50 text-brand-700" : "border-slate-200 text-slate-600"
                }`}
              >
                <input type="radio" className="sr-only" checked={sendChoice === "now"} onChange={() => setSendChoice("now")} />
                Send Now
              </label>
              <label
                className={`flex-1 rounded-lg border px-4 py-3 cursor-pointer text-center text-sm font-medium ${
                  sendChoice === "schedule"
                    ? "border-brand-500 bg-brand-50 text-brand-700"
                    : "border-slate-200 text-slate-600"
                }`}
              >
                <input
                  type="radio"
                  className="sr-only"
                  checked={sendChoice === "schedule"}
                  onChange={() => setSendChoice("schedule")}
                />
                Schedule for Later
              </label>
            </div>

            {sendChoice === "schedule" && (
              <DateTimeTimezonePicker
                date={scheduleValue.date}
                time={scheduleValue.time}
                timezone={scheduleValue.timezone}
                onChange={setScheduleValue}
              />
            )}

            {scheduleError && (
              <div className="rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">
                {scheduleError}
              </div>
            )}

            <dl className="divide-y divide-slate-100 text-sm rounded-lg border border-slate-200 px-4">
              <Row label="Campaign Name" value={form.name} />
              <Row label="Subject" value={form.subject} />
              <Row label="Sender" value={`${form.sender_name} <${form.sender_email}>`} />
              <Row label="Template" value={selectedTemplate?.name || "—"} />
              <Row label="Recipients" value={`${totalRecipients} contacts`} />
              {sendChoice === "schedule" && (
                <>
                  <Row label="Scheduled Date" value={scheduleValue.date} />
                  <Row label="Scheduled Time" value={scheduleValue.time} />
                  <Row label="Timezone" value={scheduleValue.timezone} />
                </>
              )}
            </dl>
          </div>
        )}
      </div>

      <div className="flex justify-between">
        <button className="btn-secondary" onClick={handleBack} disabled={step === 0}>
          Back
        </button>
        {step < STEPS.length - 1 ? (
          <button className="btn-primary" onClick={handleNext} disabled={!canProceed()}>
            Next
          </button>
        ) : (
          <button className="btn-primary" onClick={handleFinalSubmit} disabled={submitting}>
            {submitting ? "Submitting…" : sendChoice === "now" ? "Send Campaign" : "Schedule Campaign"}
          </button>
        )}
      </div>
    </div>
  );
}

function Row({ label, value }) {
  return (
    <div className="flex justify-between py-2.5">
      <dt className="text-slate-500">{label}</dt>
      <dd className="text-slate-900 font-medium text-right">{value}</dd>
    </div>
  );
}

