// Display names for email providers. The backend is the source of truth for which providers exist and
// which are usable (GET /campaigns/providers/); this only maps a provider's id to a readable label.
export const PROVIDER_NAMES = ["brevo", "smtp", "sendpulse"];
export const PROVIDER_LABELS = { brevo: "Brevo", smtp: "Our own SMTP server", sendpulse: "SendPulse" };
export const providerLabel = (name) => PROVIDER_LABELS[name] || name;
