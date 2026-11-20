import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import ConfirmDialog from "../components/ConfirmDialog";
import Dropdown, { MenuItem } from "../components/Dropdown";
import EmptyState from "../components/EmptyState";
import Icon from "../components/Icon";
import Modal from "../components/Modal";
import PageHeader from "../components/PageHeader";
import SearchBar from "../components/SearchBar";
import { Skeleton } from "../components/Skeleton";
import { useToast } from "../context/ToastContext";
import { deleteTemplate, duplicateTemplate, listTemplates } from "../services/templateService";

// Sandboxed, scaled-down live preview of the template's own HTML (no scripts run inside the frame).
function Thumb({ html, title }) {
  return (
    <div className="relative h-44 overflow-hidden border-b border-slate-100 bg-slate-100">
      <iframe title={`Preview of ${title}`} sandbox="" srcDoc={html || "<p style='font-family:sans-serif;color:#94a3b8;padding:16px'>Empty template</p>"} tabIndex={-1}
        className="pointer-events-none absolute left-0 top-0 h-[700px] w-[800px] origin-top-left scale-[0.42] border-0 bg-white sm:scale-[0.4]" />
    </div>
  );
}

export default function TemplatesPage() {
  const { showToast } = useToast();
  const navigate = useNavigate();
  const [templates, setTemplates] = useState([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [confirmDelete, setConfirmDelete] = useState(null);
  const [preview, setPreview] = useState(null);

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
      <PageHeader
        title="Email templates"
        subtitle="Reusable designs for your campaigns."
        actions={<button className="btn-primary" onClick={() => navigate("/templates/create")}><Icon name="plus" className="h-4 w-4" /> Create template</button>}
      />

      <SearchBar value={search} onChange={setSearch} placeholder="Search templates…" className="max-w-sm" />

      {loading ? (
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="card overflow-hidden"><Skeleton className="h-44 rounded-none" /><div className="space-y-2 p-4"><Skeleton className="h-4 w-2/3" /><Skeleton className="h-3 w-1/2" /></div></div>
          ))}
        </div>
      ) : templates.length === 0 ? (
        <div className="card">
          <EmptyState
            icon="template"
            title={search ? "No templates match your search" : "No templates yet"}
            description={search ? "Try a different search term." : "Create your first email template to start building campaigns."}
            action={!search && <button className="btn-primary" onClick={() => navigate("/templates/create")}><Icon name="plus" className="h-4 w-4" /> Create template</button>}
          />
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-3">
          {templates.map((t) => (
            <div key={t.id} className="card group flex flex-col overflow-hidden transition hover:border-brand-300 hover:shadow-pop">
              <button type="button" onClick={() => setPreview(t)} className="block text-left" aria-label={`Preview ${t.name}`}><Thumb html={t.html_content} title={t.name} /></button>
              <div className="flex flex-1 flex-col p-4">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <h3 className="truncate text-sm font-semibold text-slate-900">{t.name}</h3>
                    <p className="mt-0.5 truncate text-xs text-slate-500">{t.subject || "No subject"}</p>
                  </div>
                  <Dropdown width="w-44" trigger={({ toggle }) => <button className="btn-icon -mr-2 -mt-1" onClick={toggle} aria-haspopup="menu" aria-label={`More actions for ${t.name}`}><Icon name="more" className="h-4 w-4" /></button>}>
                    <MenuItem onClick={() => setPreview(t)}><Icon name="eye" className="h-4 w-4" /> Preview</MenuItem>
                    <MenuItem onClick={() => handleDuplicate(t.id)}><Icon name="copy" className="h-4 w-4" /> Duplicate</MenuItem>
                    <MenuItem danger onClick={() => setConfirmDelete(t)}><Icon name="trash" className="h-4 w-4" /> Delete</MenuItem>
                  </Dropdown>
                </div>
                <div className="mt-4 flex gap-2">
                  <Link to={`/templates/${t.id}/edit`} className="btn-secondary btn-sm flex-1"><Icon name="edit" className="h-3.5 w-3.5" /> Edit</Link>
                  <button className="btn-ghost btn-sm" onClick={() => setPreview(t)}><Icon name="eye" className="h-3.5 w-3.5" /> Preview</button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      <Modal open={!!preview} onClose={() => setPreview(null)} title={preview?.name || "Preview"} size="xl"
        footer={<><button className="btn-secondary" onClick={() => setPreview(null)}>Close</button>{preview && <Link to={`/templates/${preview.id}/edit`} className="btn-primary">Edit template</Link>}</>}>
        {preview?.subject && <p className="mb-3 text-sm text-slate-500">Subject: <span className="font-medium text-slate-900">{preview.subject}</span></p>}
        <iframe title="Template preview" sandbox="" srcDoc={preview?.html_content || ""} className="h-[60vh] w-full rounded-lg border border-slate-200 bg-white" />
      </Modal>

      <ConfirmDialog
        open={!!confirmDelete}
        onClose={() => setConfirmDelete(null)}
        onConfirm={handleDelete}
        title="Delete this template?"
        message={`“${confirmDelete?.name}” will be permanently removed.`}
        confirmLabel="Delete template"
      />
    </div>
  );
}
