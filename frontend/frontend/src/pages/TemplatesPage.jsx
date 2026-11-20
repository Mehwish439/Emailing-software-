import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import ConfirmDialog from "../components/ConfirmDialog";
import EmptyState from "../components/EmptyState";
import Spinner from "../components/Spinner";
import { useToast } from "../context/ToastContext";
import { deleteTemplate, duplicateTemplate, listTemplates } from "../services/templateService";

export default function TemplatesPage() {
  const { showToast } = useToast();
  const navigate = useNavigate();
  const [templates, setTemplates] = useState([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [confirmDelete, setConfirmDelete] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const data = await listTemplates({ search: search || undefined });
      setTemplates(data.results || []);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const t = setTimeout(load, 250);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  const handleDuplicate = async (id) => {
    try {
      await duplicateTemplate(id);
      showToast("Template duplicated.", "success");
      load();
    } catch {
      showToast("Failed to duplicate template.", "error");
    }
  };

  const handleDelete = async () => {
    try {
      await deleteTemplate(confirmDelete.id);
      showToast("Template deleted.", "success");
      setConfirmDelete(null);
      load();
    } catch {
      showToast("Failed to delete template.", "error");
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Email Templates</h1>
          <p className="text-sm text-slate-500">Reusable content for your campaigns.</p>
        </div>
        <button className="btn-primary" onClick={() => navigate("/templates/create")}>
          Create Template
        </button>
      </div>

      <input
        className="input max-w-xs"
        placeholder="Search templates…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />

      {loading ? (
        <div className="flex justify-center py-16">
          <Spinner size="lg" />
        </div>
      ) : templates.length === 0 ? (
        <div className="card">
          <EmptyState
            title="No templates yet"
            description="Create your first email template to start building campaigns."
            action={
              <button className="btn-primary" onClick={() => navigate("/templates/create")}>
                Create Template
              </button>
            }
          />
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {templates.map((t) => (
            <div key={t.id} className="card p-5 flex flex-col">
              <h3 className="text-sm font-semibold text-slate-900">{t.name}</h3>
              <p className="text-xs text-slate-500 mt-1">{t.subject}</p>
              <div
                className="mt-3 h-24 overflow-hidden rounded-lg border border-slate-100 bg-slate-50 p-2 text-xs text-slate-500"
                dangerouslySetInnerHTML={{ __html: t.html_content }}
              />
              <div className="mt-4 flex items-center gap-3 text-sm">
                <Link to={`/templates/${t.id}/edit`} className="text-brand-600 hover:underline">
                  Edit
                </Link>
                <button className="text-slate-600 hover:underline" onClick={() => handleDuplicate(t.id)}>
                  Duplicate
                </button>
                <button className="text-red-600 hover:underline ml-auto" onClick={() => setConfirmDelete(t)}>
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      <ConfirmDialog
        open={!!confirmDelete}
        onClose={() => setConfirmDelete(null)}
        onConfirm={handleDelete}
        title="Delete this template?"
        message={`"${confirmDelete?.name}" will be permanently removed.`}
        confirmLabel="Delete"
      />
    </div>
  );
}
