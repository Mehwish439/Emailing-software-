import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import Modal from "../components/Modal";
import { useToast } from "../context/ToastContext";
import { createTemplate, getTemplate, updateTemplate } from "../services/templateService";

const UNSUBSCRIBE_SNIPPET = `<p style="font-size:12px;color:#94a3b8;text-align:center;margin-top:32px;">
  Don't want these emails? <a href="{{unsubscribe_url}}" style="color:#94a3b8;text-decoration:underline;">Unsubscribe</a>
</p>`;

const STARTER_HTML = `<div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;">
  <h1 style="color: #2b47dd;">Hello {{first_name}}!</h1>
  <p>Write your email content here.</p>
  <p><a href="#" style="color: #2b47dd;">Call to action</a></p>
${UNSUBSCRIBE_SNIPPET}
</div>`;

export default function TemplateEditorPage() {
  const { id } = useParams();
  const isEditing = !!id;
  const navigate = useNavigate();
  const { showToast } = useToast();
  const textareaRef = useRef(null);

  const [form, setForm] = useState({ name: "", subject: "", html_content: STARTER_HTML });
  const [loading, setLoading] = useState(isEditing);
  const [saving, setSaving] = useState(false);
  const [showPreview, setShowPreview] = useState(true);

  const [imageModalOpen, setImageModalOpen] = useState(false);
  const [imageUrl, setImageUrl] = useState("");
  const [imageAlt, setImageAlt] = useState("");

  useEffect(() => {
    if (isEditing) {
      getTemplate(id).then((data) => {
        setForm({ name: data.name, subject: data.subject, html_content: data.html_content });
        setLoading(false);
      });
    }
  }, [id, isEditing]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      if (isEditing) {
        await updateTemplate(id, form);
        showToast("Template updated.", "success");
      } else {
        await createTemplate(form);
        showToast("Template created.", "success");
      }
      navigate("/templates");
    } catch (err) {
      showToast(err.response?.data?.html_content?.[0] || "Failed to save template.", "error");
    } finally {
      setSaving(false);
    }
  };

  // Inserts a snippet at the current cursor position in the HTML textarea
  // (or appends to the end if the textarea isn't focused/no selection is known).
  const insertAtCursor = (snippet) => {
    const el = textareaRef.current;
    if (!el) {
      setForm((prev) => ({ ...prev, html_content: prev.html_content + "\n" + snippet }));
      return;
    }
    const start = el.selectionStart ?? el.value.length;
    const end = el.selectionEnd ?? el.value.length;
    setForm((prev) => {
      const before = prev.html_content.slice(0, start);
      const after = prev.html_content.slice(end);
      return { ...prev, html_content: `${before}${snippet}${after}` };
    });
    // Restore focus + move cursor to just after the inserted snippet on the next tick.
    requestAnimationFrame(() => {
      el.focus();
      const newPos = start + snippet.length;
      el.setSelectionRange(newPos, newPos);
    });
  };

  const insertUnsubscribeLink = () => {
    if (form.html_content.includes("{{unsubscribe_url}}")) {
      showToast("This template already has an unsubscribe link.", "info");
      return;
    }
    insertAtCursor(`\n${UNSUBSCRIBE_SNIPPET}\n`);
  };

  const openImageModal = () => {
    setImageUrl("");
    setImageAlt("");
    setImageModalOpen(true);
  };

  const handleInsertImage = () => {
    if (!imageUrl.trim()) return;
    const alt = imageAlt.trim() || "Image";
    insertAtCursor(`<img src="${imageUrl.trim()}" alt="${alt}" style="max-width:100%;height:auto;display:block;" />`);
    setImageModalOpen(false);
  };

  if (loading) return null;

  const hasUnsubscribeLink = form.html_content.includes("{{unsubscribe_url}}");

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">{isEditing ? "Edit Template" : "Create Template"}</h1>
          <p className="text-sm text-slate-500">Design the content used inside your campaigns.</p>
        </div>
        <div className="flex gap-2">
          <button className="btn-secondary" onClick={() => navigate("/templates")}>
            Cancel
          </button>
          <button className="btn-primary" onClick={handleSubmit} disabled={saving}>
            {saving ? "Saving…" : "Save Template"}
          </button>
        </div>
      </div>

      <form className="grid grid-cols-1 lg:grid-cols-2 gap-6" onSubmit={handleSubmit}>
        <div className="card p-5 space-y-4">
          <div>
            <label className="label">Template name</label>
            <input
              className="input"
              required
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
          </div>
          <div>
            <label className="label">Subject line</label>
            <input
              className="input"
              required
              value={form.subject}
              onChange={(e) => setForm({ ...form, subject: e.target.value })}
            />
          </div>

          {!hasUnsubscribeLink && (
            <div className="rounded-lg bg-amber-50 border border-amber-200 px-3 py-2 text-xs text-amber-800">
              This template has no unsubscribe link. Emails without one are far more likely to land in spam, and
              most regions require one by law. Click "Insert unsubscribe link" below to add one.
            </div>
          )}

          <div>
            <div className="flex items-center justify-between mb-1 flex-wrap gap-2">
              <label className="label mb-0">HTML content</label>
              <div className="flex items-center gap-3">
                <button type="button" className="text-xs text-brand-600 hover:underline" onClick={openImageModal}>
                  Insert image
                </button>
                <button type="button" className="text-xs text-brand-600 hover:underline" onClick={insertUnsubscribeLink}>
                  Insert unsubscribe link
                </button>
                <button
                  type="button"
                  className="text-xs text-brand-600 hover:underline"
                  onClick={() => setShowPreview((p) => !p)}
                >
                  {showPreview ? "Hide preview" : "Show preview"}
                </button>
              </div>
            </div>
            <textarea
              ref={textareaRef}
              className="input font-mono text-xs"
              rows={16}
              required
              value={form.html_content}
              onChange={(e) => setForm({ ...form, html_content: e.target.value })}
            />
            <p className="mt-1 text-xs text-slate-400">
              Basic HTML formatting is supported. Use <code>{"{{first_name}}"}</code> and{" "}
              <code>{"{{unsubscribe_url}}"}</code> as merge tags — they're filled in per-recipient when a campaign
              sends.
            </p>
          </div>
        </div>

        {showPreview && (
          <div className="card p-5">
            <p className="label">Live preview</p>
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
              <p className="text-xs text-slate-400 mb-2">Subject: {form.subject || "(no subject)"}</p>
              <div
                className="bg-white rounded-lg p-4 min-h-[300px]"
                dangerouslySetInnerHTML={{ __html: form.html_content.replace(/\{\{unsubscribe_url\}\}/g, "#") }}
              />
            </div>
          </div>
        )}
      </form>

      <Modal
        open={imageModalOpen}
        onClose={() => setImageModalOpen(false)}
        title="Insert Image"
        footer={
          <>
            <button className="btn-secondary" onClick={() => setImageModalOpen(false)}>
              Cancel
            </button>
            <button className="btn-primary" onClick={handleInsertImage} disabled={!imageUrl.trim()}>
              Insert
            </button>
          </>
        }
      >
        <div className="space-y-4">
          <p className="text-sm text-slate-500">
            Email clients can't display images uploaded from your computer directly — images must be hosted
            somewhere reachable on the internet and linked by URL. Upload your image to any image host (e.g. your
            website, a CDN, or an image hosting service) first, then paste its URL below.
          </p>
          <div>
            <label className="label">Image URL</label>
            <input
              className="input"
              type="url"
              placeholder="https://example.com/image.png"
              value={imageUrl}
              onChange={(e) => setImageUrl(e.target.value)}
            />
          </div>
          <div>
            <label className="label">Alt text (optional, recommended)</label>
            <input
              className="input"
              placeholder="Describes the image for accessibility and when images are blocked"
              value={imageAlt}
              onChange={(e) => setImageAlt(e.target.value)}
            />
          </div>
          {imageUrl.trim() && (
            <div className="rounded-lg border border-slate-200 p-2">
              <p className="text-xs text-slate-400 mb-1">Preview</p>
              {/* eslint-disable-next-line jsx-a11y/alt-text */}
              <img src={imageUrl} alt={imageAlt || "Preview"} className="max-w-full max-h-40 object-contain mx-auto" />
            </div>
          )}
        </div>
      </Modal>
    </div>
  );
}
