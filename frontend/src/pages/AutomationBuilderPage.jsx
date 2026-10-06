// NEW FILE (Marketing Automation feature)
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import Spinner from "../components/Spinner";
import StatusBadge from "../components/StatusBadge";
import { useToast } from "../context/ToastContext";
import {
  activateAutomation,
  createAutomation,
  getAutomation,
  updateAutomation,
} from "../services/automationService";
import { listContactLists, listTags } from "../services/contactService";
import { listSignupForms } from "../services/signupFormService";
import { listTemplates } from "../services/templateService";
import { ACTION_OPTIONS, apiErrorMessage, TRIGGER_OPTIONS, UNIT_OPTIONS } from "../utils/automation";

const newStep = (order) => ({
  action_type: "send_email",
  email_template: "",
  delay_value: order === 1 ? 0 : 1,
  delay_unit: "days",
  subject: "",
  condition_mode: "always", // always | has_tag | not_has_tag
  condition_tag: "",
});

// API step -> editable form step
function fromApiStep(step) {
  const cfg = step.configuration || {};
  const cond = cfg.condition;
  return {
    action_type: step.action_type,
    email_template: step.email_template || "",
    delay_value: step.delay_value,
    delay_unit: step.delay_unit,
    subject: cfg.subject || "",
    condition_mode: cond?.type === "has_tag" ? (cond.negate ? "not_has_tag" : "has_tag") : "always",
    condition_tag: cond?.tag_id || "",
  };
}

// Editable form step -> API step
function toApiStep(step) {
  const configuration = {};
  if (step.action_type === "send_email" && step.subject.trim()) configuration.subject = step.subject.trim();
  if (step.action_type === "send_email" && step.condition_mode !== "always" && step.condition_tag) {
    configuration.condition = {
      type: "has_tag",
      tag_id: Number(step.condition_tag),
      negate: step.condition_mode === "not_has_tag",
    };
  }
  return {
    action_type: step.action_type,
    email_template: step.action_type === "send_email" ? Number(step.email_template) || null : null,
    delay_value: Number(step.delay_value) || 0,
    delay_unit: step.delay_unit,
    configuration,
  };
}

export default function AutomationBuilderPage() {
  const { id } = useParams();
  const isEdit = !!id;
  const navigate = useNavigate();
  const { showToast } = useToast();

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState("draft");

  const [templates, setTemplates] = useState([]);
  const [forms, setForms] = useState([]);
  const [lists, setLists] = useState([]);
  const [tags, setTags] = useState([]);

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [triggerType, setTriggerType] = useState("signup_form_submitted");
  const [signupFormId, setSignupFormId] = useState("");
  const [listId, setListId] = useState("");
  const [senderName, setSenderName] = useState("");
  const [senderEmail, setSenderEmail] = useState("");
  const [allowReenrollment, setAllowReenrollment] = useState(false);
  const [steps, setSteps] = useState([newStep(1)]);

  // An ACTIVE automation has contacts mid-flight, so its trigger/steps are locked until paused.
  const workflowLocked = isEdit && status === "active";

  useEffect(() => {
    (async () => {
      try {
        const [t, f, l, tg] = await Promise.all([
          listTemplates({ page_size: 200 }),
          listSignupForms({ page_size: 200 }),
          listContactLists({ page_size: 200 }),
          listTags({ page_size: 200 }),
        ]);
        setTemplates(t.results || t || []);
        setForms(f.results || f || []);
        setLists(l.results || l || []);
        setTags(tg.results || tg || []);

        if (isEdit) {
          const a = await getAutomation(id);
          setStatus(a.status);
          setName(a.name);
          setDescription(a.description || "");
          setTriggerType(a.trigger_type);
          setSignupFormId(a.trigger_config?.signup_form_id || "");
          setListId(a.trigger_config?.list_id || "");
          setSenderName(a.sender_name || "");
          setSenderEmail(a.sender_email || "");
          setAllowReenrollment(!!a.allow_reenrollment);
          setSteps(a.steps.length ? a.steps.map(fromApiStep) : [newStep(1)]);
        }
      } catch (err) {
        showToast(apiErrorMessage(err, "Failed to load the builder."), "error");
      } finally {
        setLoading(false);
      }
    })();
  }, [id, isEdit, showToast]);

  const updateStep = (index, patch) => setSteps((prev) => prev.map((s, i) => (i === index ? { ...s, ...patch } : s)));
  const addStep = () => setSteps((prev) => [...prev, newStep(prev.length + 1)]);
  const removeStep = (index) => setSteps((prev) => prev.filter((_, i) => i !== index));
  const moveStep = (index, dir) =>
    setSteps((prev) => {
      const target = index + dir;
      if (target < 0 || target >= prev.length) return prev;
      const copy = [...prev];
      [copy[index], copy[target]] = [copy[target], copy[index]];
      return copy;
    });

  const validate = () => {
    if (!name.trim()) return "Give the automation a name.";
    if (triggerType === "signup_form_submitted" && !signupFormId) return "Choose the signup form.";
    if (triggerType === "contact_added" && !listId) return "Choose the list.";
    if (steps.length === 0) return "Add at least one step.";
    for (let i = 0; i < steps.length; i++) {
      const s = steps[i];
      if (s.action_type === "send_email" && !s.email_template) return `Step ${i + 1}: choose a template.`;
      if (s.action_type === "wait" && !(Number(s.delay_value) > 0)) return `Step ${i + 1}: a Wait step needs a delay above 0.`;
      if (s.action_type === "send_email" && s.condition_mode !== "always" && !s.condition_tag)
        return `Step ${i + 1}: choose a tag for the condition.`;
    }
    return null;
  };

  const buildPayload = () => {
    const base = {
      name: name.trim(),
      description,
      sender_name: senderName.trim(),
      sender_email: senderEmail.trim(),
      allow_reenrollment: allowReenrollment,
    };
    if (workflowLocked) return base; // trigger + steps are read-only while active
    return {
      ...base,
      trigger_type: triggerType,
      trigger_config:
        triggerType === "signup_form_submitted"
          ? { signup_form_id: Number(signupFormId) }
          : triggerType === "contact_added"
          ? { list_id: Number(listId) }
          : {},
      steps: steps.map(toApiStep),
    };
  };

  const save = async ({ activate }) => {
    const problem = workflowLocked ? (name.trim() ? null : "Give the automation a name.") : validate();
    if (problem) {
      showToast(problem, "error");
      return;
    }
    setSaving(true);
    try {
      const payload = buildPayload();
      const saved = isEdit ? await updateAutomation(id, payload) : await createAutomation(payload);
      if (activate && saved.status !== "active") {
        await activateAutomation(saved.id);
        showToast("Automation saved and activated.", "success");
      } else {
        showToast(isEdit ? "Automation updated." : "Draft saved.", "success");
      }
      navigate(`/automations/${saved.id}`);
    } catch (err) {
      showToast(apiErrorMessage(err, "Failed to save automation."), "error");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex justify-center py-24">
        <Spinner size="lg" />
      </div>
    );
  }

  return (
    <div className="max-w-3xl space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <Link to="/automations" className="text-sm text-brand-600 hover:underline">
            ← Automations
          </Link>
          <h1 className="mt-1 text-2xl font-semibold text-slate-900 flex items-center gap-3">
            {isEdit ? "Edit Automation" : "Create Automation"}
            {isEdit && <StatusBadge status={status} />}
          </h1>
        </div>
      </div>

      {workflowLocked && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          This automation is active and has contacts moving through it, so its trigger and steps are locked. Pause it from the
          automation page to change them.
        </div>
      )}

      <div className="card p-6 space-y-4">
        <div>
          <label className="label">Name</label>
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Welcome New Subscribers" />
        </div>
        <div>
          <label className="label">Description (optional)</label>
          <input className="input" value={description} onChange={(e) => setDescription(e.target.value)} />
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="label">Trigger</label>
            <select className="input" value={triggerType} disabled={workflowLocked} onChange={(e) => setTriggerType(e.target.value)}>
              {TRIGGER_OPTIONS.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </div>
          {triggerType === "signup_form_submitted" && (
            <div>
              <label className="label">Signup form</label>
              <select className="input" value={signupFormId} disabled={workflowLocked} onChange={(e) => setSignupFormId(e.target.value)}>
                <option value="">Select a form…</option>
                {forms.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.name}
                  </option>
                ))}
              </select>
            </div>
          )}
          {triggerType === "contact_added" && (
            <div>
              <label className="label">List</label>
              <select className="input" value={listId} disabled={workflowLocked} onChange={(e) => setListId(e.target.value)}>
                <option value="">Select a list…</option>
                {lists.map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.name}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>

        {triggerType === "cart_abandoned" && (
          <p className="text-sm text-slate-500">
            Starts when your store (or any integration) sends a <code>cart_abandoned</code> event to{" "}
            <code>POST /api/automations/events/</code>. No store is connected yet — the automation will wait for that event.
          </p>
        )}
      </div>

      <div className="space-y-3">
        {steps.map((step, index) => (
          <div key={index} className="card p-5 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-slate-900">Step {index + 1}</h3>
              {!workflowLocked && (
                <div className="flex items-center gap-3 text-sm">
                  <button className="text-slate-500 hover:text-slate-800 disabled:opacity-30" disabled={index === 0} onClick={() => moveStep(index, -1)}>
                    ↑ Up
                  </button>
                  <button
                    className="text-slate-500 hover:text-slate-800 disabled:opacity-30"
                    disabled={index === steps.length - 1}
                    onClick={() => moveStep(index, 1)}
                  >
                    ↓ Down
                  </button>
                  <button className="text-red-600 hover:underline disabled:opacity-30" disabled={steps.length === 1} onClick={() => removeStep(index)}>
                    Remove
                  </button>
                </div>
              )}
            </div>

            <fieldset disabled={workflowLocked} className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="label">Action</label>
                  <select className="input" value={step.action_type} onChange={(e) => updateStep(index, { action_type: e.target.value })}>
                    {ACTION_OPTIONS.map((a) => (
                      <option key={a.value} value={a.value}>
                        {a.label}
                      </option>
                    ))}
                  </select>
                </div>
                {step.action_type === "send_email" && (
                  <div>
                    <label className="label">Template</label>
                    <select className="input" value={step.email_template} onChange={(e) => updateStep(index, { email_template: e.target.value })}>
                      <option value="">Select a template…</option>
                      {templates.map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.name}
                        </option>
                      ))}
                    </select>
                  </div>
                )}
              </div>

              <div>
                <label className="label">{step.action_type === "wait" ? "Wait for" : "Delay before this step"}</label>
                <div className="flex gap-2 max-w-xs">
                  <input
                    type="number"
                    min="0"
                    className="input"
                    value={step.delay_value}
                    onChange={(e) => updateStep(index, { delay_value: e.target.value })}
                  />
                  <select className="input" value={step.delay_unit} onChange={(e) => updateStep(index, { delay_unit: e.target.value })}>
                    {UNIT_OPTIONS.map((u) => (
                      <option key={u.value} value={u.value}>
                        {u.label}
                      </option>
                    ))}
                  </select>
                </div>
                <p className="mt-1 text-xs text-slate-500">
                  {index === 0 ? "Counted from the moment the contact enters the automation. 0 = immediately." : "Counted from when the previous step finished."}
                </p>
              </div>

              {step.action_type === "send_email" && (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label className="label">Subject override (optional)</label>
                    <input
                      className="input"
                      value={step.subject}
                      onChange={(e) => updateStep(index, { subject: e.target.value })}
                      placeholder="Uses the template's subject if empty"
                    />
                  </div>
                  <div>
                    <label className="label">Only send if contact…</label>
                    <div className="flex gap-2">
                      <select className="input" value={step.condition_mode} onChange={(e) => updateStep(index, { condition_mode: e.target.value })}>
                        <option value="always">Always</option>
                        <option value="has_tag">Has tag</option>
                        <option value="not_has_tag">Does not have tag</option>
                      </select>
                      {step.condition_mode !== "always" && (
                        <select className="input" value={step.condition_tag} onChange={(e) => updateStep(index, { condition_tag: e.target.value })}>
                          <option value="">Tag…</option>
                          {tags.map((t) => (
                            <option key={t.id} value={t.id}>
                              {t.name}
                            </option>
                          ))}
                        </select>
                      )}
                    </div>
                  </div>
                </div>
              )}
            </fieldset>
          </div>
        ))}

        {!workflowLocked && (
          <button className="btn-secondary w-full" onClick={addStep}>
            + Add step
          </button>
        )}
      </div>

      <div className="card p-6 space-y-4">
        <h3 className="text-sm font-semibold text-slate-900">Sender &amp; options</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="label">Sender name (optional)</label>
            <input className="input" value={senderName} onChange={(e) => setSenderName(e.target.value)} placeholder="Uses your default sender" />
          </div>
          <div>
            <label className="label">Sender email (optional)</label>
            <input className="input" type="email" value={senderEmail} onChange={(e) => setSenderEmail(e.target.value)} placeholder="Uses your default sender" />
          </div>
        </div>
        <p className="text-xs text-slate-500">The sender address must be a verified sender in Brevo.</p>
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input type="checkbox" checked={allowReenrollment} onChange={(e) => setAllowReenrollment(e.target.checked)} />
          Allow a contact to go through this automation again after finishing it
        </label>
      </div>

      <div className="flex justify-end gap-2 pb-8">
        <button className="btn-secondary" disabled={saving} onClick={() => navigate(isEdit ? `/automations/${id}` : "/automations")}>
          Cancel
        </button>
        <button className="btn-secondary" disabled={saving} onClick={() => save({ activate: false })}>
          {saving ? "Saving…" : isEdit ? "Save Changes" : "Save Draft"}
        </button>
        {status !== "active" && (
          <button className="btn-primary" disabled={saving} onClick={() => save({ activate: true })}>
            {isEdit ? "Save & Activate" : "Activate"}
          </button>
        )}
      </div>
    </div>
  );
}
