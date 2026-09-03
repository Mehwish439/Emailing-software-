import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import Modal from "../components/Modal";
import Spinner from "../components/Spinner";
import { useToast } from "../context/ToastContext";
import {
  createTemplate,
  getTemplate,
  listStarterTemplates,
  updateTemplate,
  uploadTemplateImage,
} from "../services/templateService";

const UNSUBSCRIBE_SNIPPET = `<p style="font-size:12px;color:#94a3b8;text-align:center;margin-top:32px;">
  Don't want these emails? <a href="{{unsubscribe_url}}" style="color:#94a3b8;text-decoration:underline;">Unsubscribe</a>
</p>`;

const BLANK_HTML = `<div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;">
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
  const fileInputRef = useRef(null);

  const [form, setForm] = useState({ name: "", subject: "", html_content: BLANK_HTML });
  const [loading, setLoading] = useState(isEditing);
  const [saving, setSaving] = useState(false);
  const [showPreview, setShowPreview] = useState(true);

  // "Start from a template" gallery — only shown when creating a new template.
  const [pickerOpen, setPickerOpen] = useState(!isEditing);
  const [starters, setStarters] = useState([]);
  const [startersLoading, setStartersLoading] = useState(!isEditing);

  const [imageModalOpen, setImageModalOpen] = useState(false);
  const [imageTab, setImageTab] = useState("upload"); // "upload" | "url"
  const [imageUrl, setImageUrl] = useState("");
  const [imageAlt, setImageAlt] = useState("");
  const [uploadingImage, setUploadingImage] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);

  useEffect(() => {
    if (isEditing) {
      getTemplate(id).then((data) => {
        setForm({ name: data.name, subject: data.subject, html_content: data.html_content });
        setLoading(false);
      });
    } else {
      listStarterTemplates()
        .then((data) => setStarters(data))
        .finally(() => setStartersLoading(false));
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

  const chooseStarter = (starter) => {
    setForm({ name: starter.name, subject: starter.subject, html_content: starter.html_content });
    setPickerOpen(false);
  };

  const chooseBlank = () => {
    setForm({ name: "", subject: "", html_content: BLANK_HTML });
    setPickerOpen(false);
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
    setImageTab("upload");
    setImageUrl("");
    setImageAlt("");
    setUploadProgress(0);
    setImageModalOpen(true);
  };

  const handleFileSelected = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadingImage(true);
    setUploadProgress(0);
    try {
      const result = await uploadTemplateImage(file, (progressEvent) => {
        if (progressEvent.total) {
          setUploadProgress(Math.round((progressEvent.loaded / progressEvent.total) * 100));
        }
      });
      const alt = imageAlt.trim() || file.name.replace(/\.[^.]+$/, "") || "Image";
      insertAtCursor(`<img src="${result.url}" alt="${alt}" style="max-width:100%;height:auto;display:block;" />`);
      showToast("Image uploaded and inserted.", "success");
      setImageModalOpen(false);
    } catch (err) {
      showToast(err.response?.data?.detail || "Failed to upload image.", "error");
    } finally {
      setUploadingImage(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleInsertImageUrl = () => {
    if (!imageUrl.trim()) return;
    const alt = imageAlt.trim() || "Image";
    insertAtCursor(`<img src="${imageUrl.trim()}" alt="${alt}" style="max-width:100%;height:auto;display:block;" />`);
    setImageModalOpen(false);
  };

  if (loading) return null;

  // --- "Start from a template" gallery (create flow only) ---
  if (pickerOpen) {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-slate-900">Create Template</h1>
            <p className="text-sm text-slate-500">Start from a template, or start blank.</p>
          </div>
          <button className="btn-secondary" onClick={() => navigate("/templates")}>
            Cancel
          </button>
        </div>

        {startersLoading ? (
          <div className="flex justify-center py-16">
            <Spinner size="lg" />
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            <button
              onClick={chooseBlank}
              className="card p-5 text-left hover:border-brand-400 hover:shadow-md transition-shadow flex flex-col items-start"
            >
              <div className="h-9 w-9 rounded-lg bg-slate-100 flex items-center justify-center mb-3 text-slate-500">
                <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.75} d="M12 4v16m8-8H4" />
                </svg>
              </div>
              <h3 className="text-sm font-semibold text-slate-900">Blank</h3>
              <p className="text-xs text-slate-500 mt-1">Start from a minimal, empty layout.</p>
            </button>

            {starters.map((s) => (
              <button
                key={s.key}
                onClick={() => chooseStarter(s)}
                className="card p-5 text-left hover:border-brand-400 hover:shadow-md transition-shadow flex flex-col items-start"
              >
                <div
                  className="w-full h-24 rounded-lg border border-slate-100 bg-slate-50 mb-3 overflow-hidden text-[6px] leading-tight pointer-events-none"
                  dangerouslySetInnerHTML={{ __html: s.html_content.replace(/\{\{unsubscribe_url\}\}/g, "#") }}
                />
                <h3 className="text-sm font-semibold text-slate-900">{s.name}</h3>
                <p className="text-xs text-slate-500 mt-1">{s.description}</p>
              </button>
            ))}
          </div>
        )}
      </div>
    );
  }

  const hasUnsubscribeLink = form.html_content.includes("{{unsubscribe_url}}");

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">{isEditing ? "Edit Template" : "Create Template"}</h1>
          <p className="text-sm text-slate-500">Design the content used inside your campaigns.</p>
        </div>
        <div className="flex gap-2">
          {!isEditing && (
            <button className="btn-secondary" onClick={() => setPickerOpen(true)}>
              Choose a different starting point
            </button>
          )}
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

      <Modal open={imageModalOpen} onClose={() => setImageModalOpen(false)} title="Insert Image">
        <div className="space-y-4">
          <div className="flex gap-1 rounded-lg bg-slate-100 p-1">
            <button
              type="button"
              onClick={() => setImageTab("upload")}
              className={`flex-1 rounded-md py-1.5 text-sm font-medium transition-colors ${
                imageTab === "upload" ? "bg-white text-slate-900 shadow-sm" : "text-slate-500"
              }`}
            >
              Upload from computer
            </button>
            <button
              type="button"
              onClick={() => setImageTab("url")}
              className={`flex-1 rounded-md py-1.5 text-sm font-medium transition-colors ${
                imageTab === "url" ? "bg-white text-slate-900 shadow-sm" : "text-slate-500"
              }`}
            >
              Use an image URL
            </button>
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

          {imageTab === "upload" ? (
            <div className="space-y-3">
              <p className="text-xs text-slate-500">PNG, JPEG, GIF, or WebP. Max 3MB.</p>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/png,image/jpeg,image/gif,image/webp"
                onChange={handleFileSelected}
                disabled={uploadingImage}
                className="input"
              />
              {uploadingImage && (
                <div className="space-y-1">
                  <div className="h-1.5 w-full rounded-full bg-slate-100 overflow-hidden">
                    <div
                      className="h-full bg-brand-600 transition-all"
                      style={{ width: `${uploadProgress}%` }}
                    />
                  </div>
                  <p className="text-xs text-slate-400">Uploading… {uploadProgress}%</p>
                </div>
              )}
            </div>
          ) : (
            <div className="space-y-3">
              <p className="text-xs text-slate-500">
                For an image already hosted somewhere (your website, a CDN, etc.), paste its URL directly.
              </p>
              <input
                className="input"
                type="url"
                placeholder="https://example.com/image.png"
                value={imageUrl}
                onChange={(e) => setImageUrl(e.target.value)}
              />
              {imageUrl.trim() && (
                <div className="rounded-lg border border-slate-200 p-2">
                  <p className="text-xs text-slate-400 mb-1">Preview</p>
                  {/* eslint-disable-next-line jsx-a11y/alt-text */}
                  <img src={imageUrl} alt={imageAlt || "Preview"} className="max-w-full max-h-40 object-contain mx-auto" />
                </div>
              )}
              <div className="flex justify-end gap-2">
                <button className="btn-secondary" onClick={() => setImageModalOpen(false)}>
                  Cancel
                </button>
                <button className="btn-primary" onClick={handleInsertImageUrl} disabled={!imageUrl.trim()}>
                  Insert
                </button>
              </div>
            </div>
          )}
        </div>
      </Modal>
    </div>
  );
}
