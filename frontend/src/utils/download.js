// Triggers a browser file download from a Blob (e.g. a PDF response body).
// Needed because these endpoints require the JWT auth header (see
// services/api.js's interceptor), so a plain <a href="..."> link can't be
// used directly — the request has to go through axios first.
export function downloadBlob(blob, filename) {
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
}

export function slugify(text) {
  return (text || "report")
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "") || "report";
}
