// NEW FILE (Signup Forms feature)
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import ConfirmDialog from "../components/ConfirmDialog";
import EmptyState from "../components/EmptyState";
import Modal from "../components/Modal";
import Spinner from "../components/Spinner";
import StatusBadge from "../components/StatusBadge";
import { useToast } from "../context/ToastContext";
import { listContactLists, listTags } from "../services/contactService";
import {
  createSignupForm,
  deleteSignupForm,
  listSignupForms,
  updateSignupForm,
} from "../services/signupFormService";

const emptyForm = {
  name: "",
  description: "",
  contact_list: "",
  tags: [],
  collect_first_name: true,
  collect_last_name: true,
  button_text: "Subscribe",
  success_message: "Thanks for subscribing! Please check your inbox to confirm.",
};

export default function SignupFormsPage() {
  const { showToast } = useToast();
  const [forms, setForms] = useState([]);
  const [lists, setLists] = useState([]);
  const [tags, setTags] = useState([]);
  const [loading, setLoading] = useState(true);

  const [formOpen, setFormOpen] = useState(false);
  const [editingForm, setEditingForm] = useState(null);
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState("");

  const [embedForm, setEmbedForm] = useState(null);
  const [copied, setCopied] = useState(false);

  const [confirmDelete, setConfirmDelete] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const data = await listSignupForms();
      setForms(data.results || data || []);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    listContactLists({ page_size: 100 }).then((data) => setLists(data.results || data || []));
    listTags({ page_size: 100 }).then((data) => setTags(data.results || data || []));
  }, []);

  const openCreateForm = () => {
    setEditingForm(null);
    setForm(emptyForm);
    setFormError("");
    setFormOpen(true);
  };

  const openEditForm = (signupForm) => {
    setEditingForm(signupForm);
    setForm({
      name: signupForm.name,
      description: signupForm.description || "",
      contact_list: signupForm.contact_list || "",
      tags: signupForm.tags || [],
      collect_first_name: signupForm.collect_first_name,
      collect_last_name: signupForm.collect_last_name,
      button_text: signupForm.button_text,
      success_message: signupForm.success_message,
    });
    setFormError("");
    setFormOpen(true);
  };

  const toggleTag = (id) => {
    setForm((prev) => ({
      ...prev,
      tags: prev.tags.includes(id) ? prev.tags.filter((x) => x !== id) : [...prev.tags, id],
    }));
  };

  const handleSave = async (e) => {
    e.preventDefault();
    setFormError("");
    setSaving(true);
    try {
      const payload = { ...form, contact_list: form.contact_list || null };
      if (editingForm) {
        await updateSignupForm(editingForm.id, payload);
        showToast("Signup form updated.", "success");
      } else {
        await createSignupForm(payload);
        showToast("Signup form created.", "success");
      }
      setFormOpen(false);
      load();
    } catch (err) {
      const data = err.response?.data;
      const message =
        data?.detail || data?.name?.[0] || data?.non_field_errors?.[0] || "Failed to save signup form.";
      setFormError(message);
    } finally {
      setSaving(false);
    }
  };

  const handleToggleActive = async (signupForm) => {
    try {
      await updateSignupForm(signupForm.id, { is_active: !signupForm.is_active });
      showToast(signupForm.is_active ? "Form deactivated." : "Form activated.", "success");
      load();
    } catch {
      showToast("Failed to update form status.", "error");
    }
  };

  const handleDelete = async () => {
    try {
      await deleteSignupForm(confirmDelete.id);
      showToast("Signup form deleted.", "success");
      setConfirmDelete(null);
      load();
    } catch {
      showToast("Failed to delete signup form.", "error");
    }
  };

  const handleCopyEmbed = async () => {
    try {
      await navigator.clipboard.writeText(embedForm.embed_code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      showToast("Couldn't copy automatically — select and copy the code manually.", "error");
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Signup Forms</h1>
          <p className="text-sm text-slate-500">
            Create an embeddable form for your website. Submissions become contacts, added to the list and{" "}
            <Link to="/contacts/tags" className="text-brand-600 hover:underline">
              tags
            </Link>{" "}
            you choose.
          </p>
        </div>
        <button className="btn-primary flex-shrink-0" onClick={openCreateForm}>
          Create Form
        </button>
      </div>

      <div className="card">
        {loading ? (
          <div className="flex justify-center py-16">
            <Spinner size="lg" />
          </div>
        ) : forms.length === 0 ? (
          <EmptyState
            title="No signup forms yet"
            description="Create a form and embed it on your website to start collecting subscribers."
            action={
              <button className="btn-primary" onClick={openCreateForm}>
                Create Form
              </button>
            }
          />
        ) : (
          <ul className="divide-y divide-slate-100">
            {forms.map((f) => (
              <li key={f.id} className="flex items-center justify-between px-5 py-4 gap-4">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-slate-900 truncate">{f.name}</p>
                  <p className="text-xs text-slate-500">
                    {f.contact_list_name ? `List: ${f.contact_list_name}` : "No list selected"} · Created{" "}
                    {new Date(f.created_at).toLocaleDateString()} · {f.submission_count} submission
                    {f.submission_count === 1 ? "" : "s"}
                  </p>
                </div>
                <div className="flex items-center gap-4 flex-shrink-0">
                  <StatusBadge status={f.is_active ? "active" : "cancelled"} />
                  <button className="text-sm text-brand-600 hover:underline" onClick={() => setEmbedForm(f)}>
                    Embed Code
                  </button>
                  <button className="text-sm text-brand-600 hover:underline" onClick={() => openEditForm(f)}>
                    Edit
                  </button>
                  <button className="text-sm text-slate-600 hover:underline" onClick={() => handleToggleActive(f)}>
                    {f.is_active ? "Deactivate" : "Activate"}
                  </button>
                  <button className="text-sm text-red-600 hover:underline" onClick={() => setConfirmDelete(f)}>
                    Delete
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      <Modal
        open={formOpen}
        onClose={() => setFormOpen(false)}
        title={editingForm ? "Edit Signup Form" : "Create Signup Form"}
        size="lg"
        footer={
          <>
            <button className="btn-secondary" onClick={() => setFormOpen(false)}>
              Cancel
            </button>
            <button className="btn-primary" onClick={handleSave} disabled={saving || !form.name.trim()}>
              {saving ? "Saving…" : editingForm ? "Save Changes" : "Create"}
            </button>
          </>
        }
      >
        <form className="space-y-4" onSubmit={handleSave}>
          {formError && <p className="text-sm text-red-600">{formError}</p>}

          <div>
            <label className="label">Form name</label>
            <input
              className="input"
              required
              autoFocus
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="e.g. Newsletter Signup"
            />
          </div>

          <div>
            <label className="label">Description (optional)</label>
            <textarea
              className="input"
              rows={2}
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
            />
          </div>

          <div>
            <label className="label">Add subscribers to list</label>
            <select
              className="input"
              value={form.contact_list}
              onChange={(e) => setForm({ ...form, contact_list: e.target.value })}
            >
              <option value="">No list</option>
              {lists.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="label">Apply tags</label>
            {tags.length === 0 ? (
              <p className="text-xs text-slate-500">
                No tags yet —{" "}
                <Link to="/contacts/tags" className="text-brand-600 hover:underline">
                  create one
                </Link>
                .
              </p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {tags.map((t) => (
                  <button
                    type="button"
                    key={t.id}
                    onClick={() => toggleTag(t.id)}
                    className={`badge cursor-pointer ${
                      form.tags.includes(t.id) ? "bg-brand-600 text-white" : "bg-slate-100 text-slate-700"
                    }`}
                  >
                    {t.name}
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="flex gap-6">
            <label className="flex items-center gap-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={form.collect_first_name}
                onChange={(e) => setForm({ ...form, collect_first_name: e.target.checked })}
              />
              Collect first name
            </label>
            <label className="flex items-center gap-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={form.collect_last_name}
                onChange={(e) => setForm({ ...form, collect_last_name: e.target.checked })}
              />
              Collect last name
            </label>
          </div>

          <div>
            <label className="label">Button text</label>
            <input
              className="input"
              maxLength={60}
              value={form.button_text}
              onChange={(e) => setForm({ ...form, button_text: e.target.value })}
            />
          </div>

          <div>
            <label className="label">Success message</label>
            <input
              className="input"
              maxLength={200}
              value={form.success_message}
              onChange={(e) => setForm({ ...form, success_message: e.target.value })}
            />
          </div>
        </form>
      </Modal>

      <Modal
        open={!!embedForm}
        onClose={() => setEmbedForm(null)}
        title="Embed Code"
        footer={
          <button className="btn-primary" onClick={handleCopyEmbed}>
            {copied ? "Copied!" : "Copy Code"}
          </button>
        }
      >
        <p className="text-sm text-slate-600 mb-3">
          Paste this snippet into your website's HTML where you want "{embedForm?.name}" to appear.
        </p>
        <pre className="bg-slate-900 text-slate-100 text-xs rounded-lg p-4 overflow-x-auto whitespace-pre-wrap">
          {embedForm?.embed_code}
        </pre>
      </Modal>

      <ConfirmDialog
        open={!!confirmDelete}
        onClose={() => setConfirmDelete(null)}
        onConfirm={handleDelete}
        title="Delete this signup form?"
        message={`"${confirmDelete?.name}" will stop accepting submissions immediately, and its embed code will no longer work. Contacts already collected will not be deleted.`}
        confirmLabel="Delete"
      />
    </div>
  );
}
