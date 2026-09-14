import { useEffect, useState } from "react";

import ConfirmDialog from "../components/ConfirmDialog";
import EmptyState from "../components/EmptyState";
import Modal from "../components/Modal";
import Spinner from "../components/Spinner";
import { useToast } from "../context/ToastContext";
import {
  createSegment,
  deleteSegment,
  getSegmentContacts,
  listContactLists,
  listSegments,
  listTags,
  updateSegment,
} from "../services/contactService";

const emptyForm = { name: "", description: "", tags: [], lists: [], status: "", tag_match: "any" };

const STATUS_OPTIONS = [
  { value: "", label: "Any status" },
  { value: "active", label: "Active" },
  { value: "unsubscribed", label: "Unsubscribed" },
  { value: "bounced", label: "Bounced" },
  { value: "blocked", label: "Blocked" },
  { value: "spam", label: "Spam" },
];

export default function SegmentsPage() {
  const { showToast } = useToast();
  const [segments, setSegments] = useState([]);
  const [tags, setTags] = useState([]);
  const [lists, setLists] = useState([]);
  const [loading, setLoading] = useState(true);

  const [formOpen, setFormOpen] = useState(false);
  const [editingSegment, setEditingSegment] = useState(null);
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);

  const [confirmDelete, setConfirmDelete] = useState(null);

  const [previewSegment, setPreviewSegment] = useState(null);
  const [previewContacts, setPreviewContacts] = useState([]);
  const [previewLoading, setPreviewLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const [segmentsData, tagsData, listsData] = await Promise.all([
        listSegments(),
        listTags({ page_size: 200 }),
        listContactLists({ page_size: 200 }),
      ]);
      setSegments(segmentsData.results || segmentsData || []);
      setTags(tagsData.results || tagsData || []);
      setLists(listsData.results || listsData || []);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const openCreateForm = () => {
    setEditingSegment(null);
    setForm(emptyForm);
    setFormOpen(true);
  };

  const openEditForm = (segment) => {
    setEditingSegment(segment);
    setForm({
      name: segment.name,
      description: segment.description || "",
      tags: segment.tags || [],
      lists: segment.lists || [],
      status: segment.status || "",
      tag_match: segment.tag_match || "any",
    });
    setFormOpen(true);
  };

  const toggleFormTag = (id) => {
    setForm((prev) => ({ ...prev, tags: prev.tags.includes(id) ? prev.tags.filter((x) => x !== id) : [...prev.tags, id] }));
  };

  const toggleFormList = (id) => {
    setForm((prev) => ({ ...prev, lists: prev.lists.includes(id) ? prev.lists.filter((x) => x !== id) : [...prev.lists, id] }));
  };

  const handleSave = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      if (editingSegment) {
        await updateSegment(editingSegment.id, form);
        showToast("Segment updated.", "success");
      } else {
        await createSegment(form);
        showToast("Segment created.", "success");
      }
      setFormOpen(false);
      load();
    } catch (err) {
      const detail = err.response?.data?.non_field_errors?.[0] || err.response?.data?.name?.[0] || "Failed to save segment.";
      showToast(detail, "error");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    try {
      await deleteSegment(confirmDelete.id);
      showToast("Segment deleted.", "success");
      setConfirmDelete(null);
      load();
    } catch {
      showToast("Failed to delete segment.", "error");
    }
  };

  const openPreview = async (segment) => {
    setPreviewSegment(segment);
    setPreviewLoading(true);
    try {
      const data = await getSegmentContacts(segment.id, { page_size: 50 });
      setPreviewContacts(data.results || []);
    } finally {
      setPreviewLoading(false);
    }
  };

  const tagName = (id) => tags.find((t) => t.id === id)?.name || `#${id}`;
  const listName = (id) => lists.find((l) => l.id === id)?.name || `#${id}`;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Segments</h1>
          <p className="text-sm text-slate-500">
            Dynamic, rule-based audiences — a segment's members update automatically as contacts' tags, lists, or
            status change, so you don't have to manually keep membership up to date. Use a segment as a campaign's
            audience alongside or instead of a static list.
          </p>
        </div>
        <button className="btn-primary flex-shrink-0" onClick={openCreateForm}>
          Create Segment
        </button>
      </div>

      <div className="card">
        {loading ? (
          <div className="flex justify-center py-16">
            <Spinner size="lg" />
          </div>
        ) : segments.length === 0 ? (
          <EmptyState
            title="No segments yet"
            description="Create a segment to target contacts by tag, list, or status — automatically kept up to date."
            action={
              <button className="btn-primary" onClick={openCreateForm}>
                Create Segment
              </button>
            }
          />
        ) : (
          <ul className="divide-y divide-slate-100">
            {segments.map((s) => (
              <li key={s.id} className="px-5 py-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-slate-900">{s.name}</p>
                    {s.description && <p className="text-xs text-slate-500 mt-0.5">{s.description}</p>}
                  </div>
                  <div className="flex items-center gap-4">
                    <span className="badge bg-brand-50 text-brand-700">{s.contact_count} contacts</span>
                    <button className="text-sm text-brand-600 hover:underline" onClick={() => openPreview(s)}>
                      View contacts
                    </button>
                    <button className="text-sm text-brand-600 hover:underline" onClick={() => openEditForm(s)}>
                      Edit
                    </button>
                    <button className="text-sm text-red-600 hover:underline" onClick={() => setConfirmDelete(s)}>
                      Delete
                    </button>
                  </div>
                </div>
                <div className="flex flex-wrap gap-1.5 mt-2">
                  {s.status && <span className="badge bg-slate-100 text-slate-600">Status: {s.status}</span>}
                  {(s.tags || []).map((id) => (
                    <span key={`tag-${id}`} className="badge bg-purple-50 text-purple-700">
                      {tagName(id)}
                    </span>
                  ))}
                  {(s.tags || []).length > 1 && (
                    <span className="badge bg-slate-100 text-slate-500">match: {s.tag_match === "all" ? "ALL tags" : "ANY tag"}</span>
                  )}
                  {(s.lists || []).map((id) => (
                    <span key={`list-${id}`} className="badge bg-sky-50 text-sky-700">
                      List: {listName(id)}
                    </span>
                  ))}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      <Modal
        open={formOpen}
        onClose={() => setFormOpen(false)}
        title={editingSegment ? "Edit Segment" : "Create Segment"}
        footer={
          <>
            <button className="btn-secondary" onClick={() => setFormOpen(false)}>
              Cancel
            </button>
            <button className="btn-primary" onClick={handleSave} disabled={saving || !form.name.trim()}>
              {saving ? "Saving…" : editingSegment ? "Save Changes" : "Create"}
            </button>
          </>
        }
      >
        <form className="space-y-4" onSubmit={handleSave}>
          <div>
            <label className="label">Segment name</label>
            <input className="input" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
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
            <label className="label">Status</label>
            <select className="input" value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
              {STATUS_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>
          {tags.length > 0 && (
            <div>
              <div className="flex items-center justify-between">
                <label className="label mb-0">Tags</label>
                {form.tags.length > 1 && (
                  <div className="flex gap-3 text-xs">
                    <label className="flex items-center gap-1">
                      <input
                        type="radio"
                        checked={form.tag_match === "any"}
                        onChange={() => setForm({ ...form, tag_match: "any" })}
                      />
                      Any selected tag
                    </label>
                    <label className="flex items-center gap-1">
                      <input
                        type="radio"
                        checked={form.tag_match === "all"}
                        onChange={() => setForm({ ...form, tag_match: "all" })}
                      />
                      All selected tags
                    </label>
                  </div>
                )}
              </div>
              <div className="space-y-1.5 max-h-32 overflow-y-auto rounded-lg border border-slate-200 p-2 mt-1">
                {tags.map((t) => (
                  <label key={t.id} className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={form.tags.includes(t.id)} onChange={() => toggleFormTag(t.id)} />
                    {t.name}
                  </label>
                ))}
              </div>
            </div>
          )}
          {lists.length > 0 && (
            <div>
              <label className="label">Lists</label>
              <div className="space-y-1.5 max-h-32 overflow-y-auto rounded-lg border border-slate-200 p-2">
                {lists.map((l) => (
                  <label key={l.id} className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={form.lists.includes(l.id)} onChange={() => toggleFormList(l.id)} />
                    {l.name}
                  </label>
                ))}
              </div>
            </div>
          )}
          <p className="text-xs text-slate-400">
            A contact matches this segment if it satisfies the status (if set) AND is in one of the selected lists (if
            any) AND matches the tag rule above (if any tags are selected). Pick at least one criterion.
          </p>
        </form>
      </Modal>

      <Modal open={!!previewSegment} onClose={() => setPreviewSegment(null)} title={`Contacts in "${previewSegment?.name}"`}>
        {previewLoading ? (
          <div className="flex justify-center py-8">
            <Spinner size="md" />
          </div>
        ) : previewContacts.length === 0 ? (
          <p className="text-sm text-slate-500 py-4">No contacts currently match this segment.</p>
        ) : (
          <ul className="divide-y divide-slate-100 max-h-96 overflow-y-auto">
            {previewContacts.map((c) => (
              <li key={c.id} className="py-2 text-sm">
                <p className="font-medium text-slate-900">{c.full_name}</p>
                <p className="text-slate-500">{c.email}</p>
              </li>
            ))}
          </ul>
        )}
      </Modal>

      <ConfirmDialog
        open={!!confirmDelete}
        onClose={() => setConfirmDelete(null)}
        onConfirm={handleDelete}
        title="Delete this segment?"
        message={`"${confirmDelete?.name}" will be removed. Any campaigns using it will no longer include it as an audience source. Contacts themselves will not be deleted.`}
        confirmLabel="Delete"
      />
    </div>
  );
}
