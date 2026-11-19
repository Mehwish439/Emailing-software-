// NEW FILE (Marketing Automation feature)
export const TRIGGER_OPTIONS = [
  { value: "signup_form_submitted", label: "Signup Form Submitted" },
  { value: "contact_added", label: "Contact Added to List" },
  { value: "cart_abandoned", label: "Cart Abandoned (external event)" },
];

export const ACTION_OPTIONS = [
  { value: "send_email", label: "Send Email" },
  { value: "wait", label: "Wait" },
  { value: "end_automation", label: "End Automation" },
];

export const UNIT_OPTIONS = [
  { value: "minutes", label: "Minutes" },
  { value: "hours", label: "Hours" },
  { value: "days", label: "Days" },
];

export const triggerLabel = (value) => TRIGGER_OPTIONS.find((t) => t.value === value)?.label || value;
export const actionLabel = (value) => ACTION_OPTIONS.find((a) => a.value === value)?.label || value;

export function formatDelay(step) {
  const n = Number(step.delay_value) || 0;
  if (n === 0) return "immediately";
  const unit = n === 1 ? step.delay_unit.replace(/s$/, "") : step.delay_unit;
  return `after ${n} ${unit}`;
}

export function formatDate(value) {
  return value ? new Date(value).toLocaleString() : "—";
}

// Pulls a readable message out of a DRF error response.
export function apiErrorMessage(err, fallback) {
  const data = err?.response?.data;
  if (!data) return fallback;
  if (typeof data === "string") return data;
  if (data.detail) return typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
  const first = Object.entries(data)[0];
  if (!first) return fallback;
  const [key, value] = first;
  const text = Array.isArray(value) ? value[0] : typeof value === "object" ? JSON.stringify(value) : value;
  return `${key}: ${text}`;
}
