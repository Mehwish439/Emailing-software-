import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { useToast } from "../context/ToastContext";
import { getCampaign, updateCampaign } from "../services/campaignService";
import { listContactLists } from "../services/contactService";
import { listTemplates } from "../services/templateService";

export default function CampaignEditPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { showToast } = useToast();

  const [form, setForm] = useState(null);
  const [templates, setTemplates] = useState([]);
  const [lists, setLists] = useState([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    (async () => {
      const [campaign, templatesData, listsData] = await Promise.all([
        getCampaign(id),
        listTemplates({ page_size: 100 }),
        listContactLists({ page_size: 100 }),
      ]);
      setForm({
        name: campaign.name,
        subject: campaign.subject,
        sender_name: campaign.sender_name,
        sender_email: campaign.sender_email,
        template: campaign.template,
        contact_lists: campaign.contact_lists,
      });
      setTemplates(templatesData.results || []);
      setLists(listsData.results || listsData || []);
    })();
  }, [id]);

  const toggleList = (listId) => {
    setForm((prev) => ({
      ...prev,
      contact_lists: prev.contact_lists.includes(listId)
        ? prev.contact_lists.filter((x) => x !== listId)
        : [...prev.contact_lists, listId],
    }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      await updateCampaign(id, form);
      showToast("Campaign updated.", "success");
      navigate(`/campaigns/${id}`);
    } catch (err) {
      showToast(err.response?.data?.detail || "Failed to update campaign.", "error");
    } finally {
      setSaving(false);
    }
  };

  if (!form) return null;

  return (
    <div className="space-y-6 max-w-2xl">
      <h1 className="text-2xl font-semibold text-slate-900">Edit Campaign</h1>

      <form className="card p-6 space-y-4" onSubmit={handleSubmit}>
        <div>
          <label className="label">Campaign name</label>
          <input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </div>
        <div>
          <label className="label">Subject line</label>
          <input className="input" value={form.subject} onChange={(e) => setForm({ ...form, subject: e.target.value })} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label">Sender name</label>
            <input
              className="input"
              value={form.sender_name}
              onChange={(e) => setForm({ ...form, sender_name: e.target.value })}
            />
          </div>
          <div>
            <label className="label">Sender email</label>
            <input
              className="input"
              type="email"
              value={form.sender_email}
              onChange={(e) => setForm({ ...form, sender_email: e.target.value })}
            />
          </div>
        </div>
        <div>
          <label className="label">Template</label>
          <select className="input" value={form.template} onChange={(e) => setForm({ ...form, template: e.target.value })}>
            {templates.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label">Contact lists</label>
          <div className="space-y-2">
            {lists.map((l) => (
              <label key={l.id} className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={form.contact_lists.includes(l.id)} onChange={() => toggleList(l.id)} />
                {l.name} <span className="text-slate-400">({l.contact_count})</span>
              </label>
            ))}
          </div>
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" className="btn-secondary" onClick={() => navigate(-1)}>
            Cancel
          </button>
          <button type="submit" className="btn-primary" disabled={saving}>
            {saving ? "Saving…" : "Save Changes"}
          </button>
        </div>
      </form>
    </div>
  );
}
