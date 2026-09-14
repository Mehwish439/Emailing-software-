import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import ConfirmDialog from "../components/ConfirmDialog";
import EmptyState from "../components/EmptyState";
import Modal from "../components/Modal";
import Spinner from "../components/Spinner";
import { useToast } from "../context/ToastContext";
import { createTag, deleteTag, listTags, updateTag } from "../services/contactService";

export default function TagsPage() {
  const { showToast } = useToast();
  const [tags, setTags] = useState([]);
  const [loading, setLoading] = useState(true);

  const [formOpen, setFormOpen] = useState(false);
  const [editingTag, setEditingTag] = useState(null);
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);

  const [confirmDelete, setConfirmDelete] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const data = await listTags();
      setTags(data.results || data || []);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const openCreateForm = () => {
    setEditingTag(null);
    setName("");
    setFormOpen(true);
  };

  const openEditForm = (tag) => {
    setEditingTag(tag);
    setName(tag.name);
    setFormOpen(true);
  };

  const handleSave = async (e) => {
    e.preventDefault();
    if (!name.trim()) return;
    setSaving(true);
    try {
      if (editingTag) {
        await updateTag(editingTag.id, { name: name.trim() });
        showToast("Tag updated.", "success");
      } else {
        await createTag({ name: name.trim() });
        showToast("Tag created.", "success");
      }
      setFormOpen(false);
      load();
    } catch (err) {
      showToast(err.response?.data?.name?.[0] || "Failed to save tag.", "error");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    try {
      await deleteTag(confirmDelete.id);
      showToast("Tag deleted.", "success");
      setConfirmDelete(null);
      load();
    } catch {
      showToast("Failed to delete tag.", "error");
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Tags</h1>
          <p className="text-sm text-slate-500">
            Flexible labels you can put on any contact (e.g. "VIP", "cold-lead") — a contact can carry several,
            and{" "}
            <Link to="/contacts/segments" className="text-brand-600 hover:underline">
              Segments
            </Link>{" "}
            let you target contacts by tag combinations automatically.
          </p>
        </div>
        <button className="btn-primary flex-shrink-0" onClick={openCreateForm}>
          Create Tag
        </button>
      </div>

      <div className="card">
        {loading ? (
          <div className="flex justify-center py-16">
            <Spinner size="lg" />
          </div>
        ) : tags.length === 0 ? (
          <EmptyState
            title="No tags yet"
            description="Create a tag, then apply it to contacts from the Contacts page."
            action={
              <button className="btn-primary" onClick={openCreateForm}>
                Create Tag
              </button>
            }
          />
        ) : (
          <ul className="divide-y divide-slate-100">
            {tags.map((t) => (
              <li key={t.id} className="flex items-center justify-between px-5 py-4">
                <p className="text-sm font-medium text-slate-900">{t.name}</p>
                <div className="flex items-center gap-4">
                  <span className="badge bg-brand-50 text-brand-700">{t.contact_count} contacts</span>
                  <Link className="text-sm text-brand-600 hover:underline" to={`/contacts?tags=${t.id}`}>
                    View contacts
                  </Link>
                  <button className="text-sm text-brand-600 hover:underline" onClick={() => openEditForm(t)}>
                    Edit
                  </button>
                  <button className="text-sm text-red-600 hover:underline" onClick={() => setConfirmDelete(t)}>
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
        title={editingTag ? "Edit Tag" : "Create Tag"}
        footer={
          <>
            <button className="btn-secondary" onClick={() => setFormOpen(false)}>
              Cancel
            </button>
            <button className="btn-primary" onClick={handleSave} disabled={saving || !name.trim()}>
              {saving ? "Saving…" : editingTag ? "Save Changes" : "Create"}
            </button>
          </>
        }
      >
        <form onSubmit={handleSave}>
          <label className="label">Tag name</label>
          <input className="input" required autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. VIP" />
        </form>
      </Modal>

      <ConfirmDialog
        open={!!confirmDelete}
        onClose={() => setConfirmDelete(null)}
        onConfirm={handleDelete}
        title="Delete this tag?"
        message={`"${confirmDelete?.name}" will be removed from any contacts that have it, and any segments using it. Contacts themselves will not be deleted.`}
        confirmLabel="Delete"
      />
    </div>
  );
}
