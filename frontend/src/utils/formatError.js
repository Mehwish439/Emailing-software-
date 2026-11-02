/**
 * Turn ANY API/network error into a safe, human-readable string.
 *
 * The backend wraps validation errors as { detail: { field: ["msg"] } } (see
 * backend/common/exceptions.py), so `detail` can be a string, an array, or a nested
 * object. Rendering such an object as a React child crashes with
 * "Objects are not valid as a React child (found: object with keys {sender_email})".
 * Always pass errors through these helpers before displaying them.
 */

const FIELD_LABELS_SKIP = new Set(["detail", "non_field_errors", "error", "message"]);

function humanizeKey(key) {
  const s = String(key).replace(/[_-]+/g, " ").trim();
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : "";
}

/** Flatten strings / arrays / nested objects into a list of messages. */
export function flattenErrors(value, path = "") {
  if (value === null || value === undefined || value === "") return [];
  if (typeof value === "string") return [path ? `${path}: ${value}` : value];
  if (typeof value === "number" || typeof value === "boolean") return [path ? `${path}: ${value}` : String(value)];
  if (Array.isArray(value)) return value.flatMap((v) => flattenErrors(v, path));
  if (typeof value === "object") {
    return Object.entries(value).flatMap(([key, v]) => {
      const label = FIELD_LABELS_SKIP.has(key) ? path : path ? `${path} › ${humanizeKey(key)}` : humanizeKey(key);
      return flattenErrors(v, label);
    });
  }
  return [];
}

/** Field-level errors as { field: "first message" } (for inline form errors). */
export function fieldErrors(err) {
  const data = err?.response?.data;
  const source = data && typeof data === "object" ? (typeof data.detail === "object" && data.detail !== null && !Array.isArray(data.detail) ? data.detail : data) : {};
  const out = {};
  Object.entries(source).forEach(([key, v]) => {
    if (FIELD_LABELS_SKIP.has(key)) return;
    const msgs = flattenErrors(v);
    if (msgs.length) out[key] = msgs[0];
  });
  return out;
}

/** Main entry point: always returns a string, never an object. */
export function formatApiError(err, fallback = "Something went wrong. Please try again.") {
  if (typeof err === "string") return err;
  if (!err) return fallback;

  if (err.response) {
    const { status, data } = err.response;
    const msgs = flattenErrors(data);
    if (msgs.length) return msgs.join(" ");
    if (status === 401) return "Your session has expired. Please sign in again.";
    if (status === 403) return "You do not have permission to do that.";
    if (status === 404) return "That item could not be found.";
    if (status === 429) return "Too many requests. Please wait a moment and try again.";
    if (status >= 500) return "The server had a problem. Please try again shortly.";
    return fallback;
  }
  if (err.request || err.code === "ERR_NETWORK" || err.message === "Network Error") {
    return "Cannot reach the server. Check your connection and try again.";
  }
  if (typeof err.message === "string" && err.message) return fallback;
  return fallback;
}

/** Last-resort guard for anything about to be rendered as a React child. */
export function toDisplayText(value, fallback = "") {
  if (value === null || value === undefined) return fallback;
  if (typeof value === "string" || typeof value === "number") return String(value);
  const msgs = flattenErrors(value);
  return msgs.length ? msgs.join(" ") : fallback;
}
