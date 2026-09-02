import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import ConfirmDialog from "../components/ConfirmDialog";
import EmptyState from "../components/EmptyState";
import Modal from "../components/Modal";
import Spinner from "../components/Spinner";
import { useToast } from "../context/ToastContext";
import { createContactList, deleteContactList, listContactLists, updateContactList } from "../services/contactService";

const emptyForm = { name: "", description: "" };

export default function ContactListsPage() {
  const { showToast } = useToast();
  const [lists, setLists] = useState([]);
  const [loading, setLoading] = useState(true);

  const [formOpen, setFormOpen] = useState(false);
  const [editingList, setEditingList] = useState(null);
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);

  const [confirmDelete, setConfirmDelete] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const data = await listContactLists();
      setLists(data.results || data || []);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const openCreateForm = () => {
    setEditingList(null);
    setForm(emptyForm);
    setFormOpen(true);
  };

  const openEditForm = (list) => {
    setEditingList(list);
    setForm({ name: list.name, description: list.description || "" });
    setFormOpen(true);
  };

  const handleSave = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      if (editingList) {
        await updateContactList(editingList.id, form);
        showToast("List updated.", "success");
      } else {
        await createContactList(form);
        showToast("List created.", "success");
      }
      setFormOpen(false);
      load();
    } catch (err) {
      showToast(err.response?.data?.name?.[0] || "Failed to save list.", "error");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    try {
      await deleteContactList(confirmDelete.id);
      showToast("List deleted.", "success");
      setConfirmDelete(null);
      load();
    } catch {
      showToast("Failed to delete list.", "error");
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Contact Lists</h1>
          <p className="text-sm text-slate-500">
            Group contacts to target with campaigns. To add contacts to a list, go to the{" "}
            <Link to="/contacts" className="text-brand-600 hover:underline">
              Contacts page
            </Link>{" "}
            and use "Add to list" (select contacts first) or assign lists when adding/editing a contact.
          </p>
        </div>
        <button className="btn-primary flex-shrink-0" onClick={openCreateForm}>
          Create List
        </button>
      </div>

      <div className="card">
        {loading ? (
          <div className="flex justify-center py-16">
            <Spinner size="lg" />
          </div>
        ) : lists.length === 0 ? (
          <EmptyState
            title="No lists yet"
            description="Create a list to organize your contacts and target them with campaigns."
            action={
              <button className="btn-primary" onClick={openCreateForm}>
                Create List
              </button>
            }
          />
        ) : (
          <ul className="divide-y divide-slate-100">
            {lists.map((l) => (
              <li key={l.id} className="flex items-center justify-between px-5 py-4">
                <div>
                  <p className="text-sm font-medium text-slate-900">{l.name}</p>
                  <p className="text-xs text-slate-500">{l.description || "No description"}</p>
                </div>
                <div className="flex items-center gap-4">
                  <span className="badge bg-brand-50 text-brand-700">{l.contact_count} contacts</span>
                  <button className="text-sm text-brand-600 hover:underline" onClick={() => openEditForm(l)}>
                    Edit
                  </button>
                  <button className="text-sm text-red-600 hover:underline" onClick={() => setConfirmDelete(l)}>
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
        title={editingList ? "Edit Contact List" : "Create Contact List"}
        footer={
          <>
            <button className="btn-secondary" onClick={() => setFormOpen(false)}>
              Cancel
            </button>
            <button className="btn-primary" onClick={handleSave} disabled={saving}>
              {saving ? "Saving…" : editingList ? "Save Changes" : "Create"}
            </button>
          </>
        }
      >
        <form className="space-y-4" onSubmit={handleSave}>
          <div>
            <label className="label">List name</label>
            <input className="input" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </div>
          <div>
            <label className="label">Description</label>
            <textarea
              className="input"
              rows={3}
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
            />
          </div>
        </form>
      </Modal>

      <ConfirmDialog
        open={!!confirmDelete}
        onClose={() => setConfirmDelete(null)}
        onConfirm={handleDelete}
        title="Delete this list?"
        message={`"${confirmDelete?.name}" will be removed. Contacts themselves will not be deleted.`}
        confirmLabel="Delete"
      />
    </div>
  );
}
