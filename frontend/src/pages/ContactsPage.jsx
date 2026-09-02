import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import ConfirmDialog from "../components/ConfirmDialog";
import EmptyState from "../components/EmptyState";
import Modal from "../components/Modal";
import Pagination from "../components/Pagination";
import Spinner from "../components/Spinner";
import StatusBadge from "../components/StatusBadge";
import { useToast } from "../context/ToastContext";
import {
  addContactsToList,
  bulkDeleteContacts,
  createContact,
  deleteContact,
  importContactsCSV,
  listContactLists,
  listContacts,
  updateContact,
} from "../services/contactService";

const emptyForm = { first_name: "", last_name: "", email: "", phone: "", status: "active", lists: [] };

export default function ContactsPage() {
  const { showToast } = useToast();
  const [contacts, setContacts] = useState([]);
  const [lists, setLists] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [page, setPage] = useState(1);
  const [numPages, setNumPages] = useState(1);
  const [selected, setSelected] = useState([]);

  const [formOpen, setFormOpen] = useState(false);
  const [editingContact, setEditingContact] = useState(null);
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);

  const [importOpen, setImportOpen] = useState(false);
  const [importFile, setImportFile] = useState(null);
  const [importListIds, setImportListIds] = useState([]);
  const [importResult, setImportResult] = useState(null);
  const [importing, setImporting] = useState(false);

  const [addToListOpen, setAddToListOpen] = useState(false);
  const [addToListId, setAddToListId] = useState("");
  const [addingToList, setAddingToList] = useState(false);

  const [confirmDelete, setConfirmDelete] = useState(null); // {type: 'single'|'bulk', id?}

  const loadLists = useCallback(async () => {
    const data = await listContactLists({ page_size: 100 });
    setLists(data.results || data || []);
  }, []);

  const loadContacts = useCallback(async () => {
    setLoading(true);
    try {
      const params = { page, search: search || undefined, status: statusFilter || undefined };
      const data = await listContacts(params);
      setContacts(data.results || []);
      setNumPages(data.num_pages || 1);
    } catch {
      showToast("Failed to load contacts.", "error");
    } finally {
      setLoading(false);
    }
  }, [page, search, statusFilter, showToast]);

  useEffect(() => {
    loadContacts();
  }, [loadContacts]);

  useEffect(() => {
    loadLists();
  }, [loadLists]);

  const openCreateForm = () => {
    setEditingContact(null);
    setForm(emptyForm);
    setFormOpen(true);
  };

  const openEditForm = (contact) => {
    setEditingContact(contact);
    setForm({
      first_name: contact.first_name,
      last_name: contact.last_name,
      email: contact.email,
      phone: contact.phone,
      status: contact.status,
      lists: contact.lists || [],
    });
    setFormOpen(true);
  };

  const toggleFormList = (listId) => {
    setForm((prev) => ({
      ...prev,
      lists: prev.lists.includes(listId) ? prev.lists.filter((x) => x !== listId) : [...prev.lists, listId],
    }));
  };

  const handleSave = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      if (editingContact) {
        await updateContact(editingContact.id, form);
        showToast("Contact updated.", "success");
      } else {
        await createContact(form);
        showToast("Contact added.", "success");
      }
      setFormOpen(false);
      loadContacts();
    } catch (err) {
      showToast(err.response?.data?.email?.[0] || err.response?.data?.detail || "Failed to save contact.", "error");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    try {
      if (confirmDelete.type === "single") {
        await deleteContact(confirmDelete.id);
        showToast("Contact deleted.", "success");
      } else {
        const result = await bulkDeleteContacts(selected);
        showToast(`Deleted ${result.deleted} contact(s).`, "success");
        setSelected([]);
      }
      setConfirmDelete(null);
      loadContacts();
    } catch {
      showToast("Delete failed.", "error");
    }
  };

  const toggleSelect = (id) => {
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  const toggleSelectAll = () => {
    setSelected((prev) => (prev.length === contacts.length ? [] : contacts.map((c) => c.id)));
  };

  const handleAddToList = async () => {
    if (!addToListId) return;
    setAddingToList(true);
    try {
      const result = await addContactsToList(addToListId, selected);
      showToast(`Added ${result.added} contact(s) to the list.`, "success");
      setAddToListOpen(false);
      setAddToListId("");
      setSelected([]);
      loadLists();
    } catch {
      showToast("Failed to add contacts to list.", "error");
    } finally {
      setAddingToList(false);
    }
  };

  const toggleImportList = (listId) => {
    setImportListIds((prev) => (prev.includes(listId) ? prev.filter((x) => x !== listId) : [...prev, listId]));
  };

  const handleImport = async () => {
    if (!importFile) return;
    setImporting(true);
    try {
      const result = await importContactsCSV(importFile, importListIds);
      setImportResult(result);
      loadContacts();
      loadLists();
    } catch (err) {
      showToast(err.response?.data?.detail || "CSV import failed.", "error");
    } finally {
      setImporting(false);
    }
  };

  const closeImportModal = () => {
    setImportOpen(false);
    setImportFile(null);
    setImportListIds([]);
    setImportResult(null);
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Contacts</h1>
          <p className="text-sm text-slate-500">Manage your subscriber base.</p>
        </div>
        <div className="flex gap-2">
          <button className="btn-secondary" onClick={() => setImportOpen(true)}>
            Import CSV
          </button>
          <button className="btn-primary" onClick={openCreateForm}>
            Add Contact
          </button>
        </div>
      </div>

      <div className="card">
        <div className="flex flex-wrap items-center gap-3 px-5 py-4 border-b border-slate-200">
          <input
            className="input max-w-xs"
            placeholder="Search contacts…"
            value={search}
            onChange={(e) => {
              setPage(1);
              setSearch(e.target.value);
            }}
          />
          <select
            className="input max-w-[160px]"
            value={statusFilter}
            onChange={(e) => {
              setPage(1);
              setStatusFilter(e.target.value);
            }}
          >
            <option value="">All statuses</option>
            <option value="active">Active</option>
            <option value="unsubscribed">Unsubscribed</option>
            <option value="bounced">Bounced</option>
            <option value="blocked">Blocked</option>
            <option value="spam">Spam</option>
          </select>
          {selected.length > 0 && (
            <div className="ml-auto flex items-center gap-2">
              <button className="btn-secondary" onClick={() => setAddToListOpen(true)}>
                Add {selected.length} to list
              </button>
              <button className="btn-danger" onClick={() => setConfirmDelete({ type: "bulk" })}>
                Delete {selected.length} selected
              </button>
            </div>
          )}
        </div>

        {loading ? (
          <div className="flex justify-center py-16">
            <Spinner size="lg" />
          </div>
        ) : contacts.length === 0 ? (
          <EmptyState
            title="No contacts found"
            description="Add your first contact or import a CSV file to get started."
            action={
              <button className="btn-primary" onClick={openCreateForm}>
                Add Contact
              </button>
            }
          />
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-200">
                <thead className="bg-slate-50">
                  <tr>
                    <th className="px-4 py-3">
                      <input
                        type="checkbox"
                        checked={selected.length === contacts.length}
                        onChange={toggleSelectAll}
                      />
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase">Name</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase">Email</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase">Phone</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase">Lists</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase">Status</th>
                    <th className="px-4 py-3" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {contacts.map((c) => (
                    <tr key={c.id} className="hover:bg-slate-50">
                      <td className="px-4 py-3">
                        <input type="checkbox" checked={selected.includes(c.id)} onChange={() => toggleSelect(c.id)} />
                      </td>
                      <td className="px-4 py-3 text-sm font-medium text-slate-900">{c.full_name}</td>
                      <td className="px-4 py-3 text-sm text-slate-600">{c.email}</td>
                      <td className="px-4 py-3 text-sm text-slate-600">{c.phone || "—"}</td>
                      <td className="px-4 py-3 text-sm text-slate-600">
                        {c.lists?.length
                          ? lists
                              .filter((l) => c.lists.includes(l.id))
                              .map((l) => l.name)
                              .join(", ") || `${c.lists.length} list(s)`
                          : "—"}
                      </td>
                      <td className="px-4 py-3">
                        <StatusBadge status={c.status} />
                      </td>
                      <td className="px-4 py-3 text-right space-x-3">
                        <button className="text-sm text-brand-600 hover:underline" onClick={() => openEditForm(c)}>
                          Edit
                        </button>
                        <button
                          className="text-sm text-red-600 hover:underline"
                          onClick={() => setConfirmDelete({ type: "single", id: c.id })}
                        >
                          Delete
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination page={page} numPages={numPages} onPageChange={setPage} />
          </>
        )}
      </div>

      {/* Add/Edit Modal */}
      <Modal
        open={formOpen}
        onClose={() => setFormOpen(false)}
        title={editingContact ? "Edit Contact" : "Add Contact"}
        footer={
          <>
            <button className="btn-secondary" onClick={() => setFormOpen(false)}>
              Cancel
            </button>
            <button className="btn-primary" onClick={handleSave} disabled={saving}>
              {saving ? "Saving…" : "Save"}
            </button>
          </>
        }
      >
        <form className="space-y-4" onSubmit={handleSave}>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label">First name</label>
              <input
                className="input"
                value={form.first_name}
                onChange={(e) => setForm({ ...form, first_name: e.target.value })}
              />
            </div>
            <div>
              <label className="label">Last name</label>
              <input
                className="input"
                value={form.last_name}
                onChange={(e) => setForm({ ...form, last_name: e.target.value })}
              />
            </div>
          </div>
          <div>
            <label className="label">Email</label>
            <input
              className="input"
              type="email"
              required
              value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
            />
          </div>
          <div>
            <label className="label">Phone</label>
            <input className="input" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
          </div>
          <div>
            <label className="label">Status</label>
            <select className="input" value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
              <option value="active">Active</option>
              <option value="unsubscribed">Unsubscribed</option>
              <option value="bounced">Bounced</option>
              <option value="blocked">Blocked</option>
              <option value="spam">Spam</option>
            </select>
          </div>
          <div>
            <label className="label">Lists</label>
            {lists.length === 0 ? (
              <p className="text-sm text-slate-500">
                No contact lists yet. Create one from the{" "}
                <Link to="/contacts/lists" className="text-brand-600 hover:underline">
                  Lists page
                </Link>{" "}
                first.
              </p>
            ) : (
              <div className="space-y-1.5 max-h-32 overflow-y-auto rounded-lg border border-slate-200 p-2">
                {lists.map((l) => (
                  <label key={l.id} className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={form.lists.includes(l.id)} onChange={() => toggleFormList(l.id)} />
                    {l.name}
                  </label>
                ))}
              </div>
            )}
          </div>
        </form>
      </Modal>

      {/* CSV Import Modal */}
      <Modal open={importOpen} onClose={closeImportModal} title="Import Contacts from CSV">
        {!importResult ? (
          <div className="space-y-4">
            <p className="text-sm text-slate-500">
              CSV must include an <span className="font-mono">email</span> column. Optional columns:{" "}
              <span className="font-mono">first_name</span>, <span className="font-mono">last_name</span>,{" "}
              <span className="font-mono">phone</span>.
            </p>
            <input type="file" accept=".csv" onChange={(e) => setImportFile(e.target.files[0])} className="input" />
            {lists.length > 0 && (
              <div>
                <label className="label">Add imported contacts to list(s) (optional)</label>
                <div className="space-y-1.5 max-h-32 overflow-y-auto rounded-lg border border-slate-200 p-2">
                  {lists.map((l) => (
                    <label key={l.id} className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={importListIds.includes(l.id)}
                        onChange={() => toggleImportList(l.id)}
                      />
                      {l.name}
                    </label>
                  ))}
                </div>
              </div>
            )}
            <div className="flex justify-end gap-2">
              <button className="btn-secondary" onClick={closeImportModal}>
                Cancel
              </button>
              <button className="btn-primary" onClick={handleImport} disabled={!importFile || importing}>
                {importing ? "Importing…" : "Import"}
              </button>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div className="rounded-lg bg-emerald-50 px-4 py-3">
                <p className="text-emerald-700 font-semibold text-lg">{importResult.imported}</p>
                <p className="text-emerald-600">Imported</p>
              </div>
              <div className="rounded-lg bg-amber-50 px-4 py-3">
                <p className="text-amber-700 font-semibold text-lg">{importResult.duplicates}</p>
                <p className="text-amber-600">Duplicates</p>
              </div>
              <div className="rounded-lg bg-red-50 px-4 py-3">
                <p className="text-red-700 font-semibold text-lg">{importResult.invalid}</p>
                <p className="text-red-600">Invalid</p>
              </div>
              <div className="rounded-lg bg-slate-100 px-4 py-3">
                <p className="text-slate-700 font-semibold text-lg">{importResult.total_processed}</p>
                <p className="text-slate-600">Total processed</p>
              </div>
            </div>
            <button className="btn-primary w-full" onClick={closeImportModal}>
              Done
            </button>
          </div>
        )}
      </Modal>

      {/* Bulk Add to List Modal */}
      <Modal
        open={addToListOpen}
        onClose={() => setAddToListOpen(false)}
        title={`Add ${selected.length} contact(s) to a list`}
        footer={
          <>
            <button className="btn-secondary" onClick={() => setAddToListOpen(false)}>
              Cancel
            </button>
            <button className="btn-primary" onClick={handleAddToList} disabled={!addToListId || addingToList}>
              {addingToList ? "Adding…" : "Add to List"}
            </button>
          </>
        }
      >
        {lists.length === 0 ? (
          <p className="text-sm text-slate-500">
            No contact lists yet. Create one from the{" "}
            <Link to="/contacts/lists" className="text-brand-600 hover:underline">
              Lists page
            </Link>{" "}
            first.
          </p>
        ) : (
          <div>
            <label className="label">List</label>
            <select className="input" value={addToListId} onChange={(e) => setAddToListId(e.target.value)}>
              <option value="">Select a list…</option>
              {lists.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name}
                </option>
              ))}
            </select>
          </div>
        )}
      </Modal>

      <ConfirmDialog
        open={!!confirmDelete}
        onClose={() => setConfirmDelete(null)}
        onConfirm={handleDelete}
        title="Delete contact(s)?"
        message="This action cannot be undone."
        confirmLabel="Delete"
      />
    </div>
  );
}
