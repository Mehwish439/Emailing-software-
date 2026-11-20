import { useEffect, useState } from "react";

import api from "../services/api";
import Icon from "./Icon";

/**
 * "Send with" menu. ALWAYS shows every provider (Brevo / our SMTP) so the choice is visible; providers the
 * account may not use, or that are not configured on the server, are greyed out with the reason.
 * The backend re-validates the choice when sending starts. No credentials are ever shown.
 */
export default function ProviderPicker({ value, onChange, disabled }) {
  const [info, setInfo] = useState(null);
  useEffect(() => { api.get("/campaigns/providers/").then((r) => setInfo(r.data)).catch(() => setInfo(null)); }, []);
  if (!info) return null;

  const current = info.options.find((o) => o.name === (value || info.default));
  const defaultLabel = info.options.find((o) => o.name === info.default)?.label || info.default;
  const blocked = info.options.filter((o) => !o.usable);

  return (
    <div className="panel-muted">
      <label className="label flex items-center gap-1.5" htmlFor="provider-pick"><Icon name="server" className="h-4 w-4 text-slate-400" /> Send with</label>
      <select id="provider-pick" className="input" disabled={disabled} value={value || ""} onChange={(e) => onChange(e.target.value)}>
        <option value="">Default — {defaultLabel}</option>
        {info.options.map((o) => (
          <option key={o.name} value={o.name} disabled={!o.usable}>{o.label}{o.usable ? "" : ` (unavailable)`}</option>
        ))}
      </select>
      {current && !current.usable && <p className="mt-1.5 text-xs text-red-600" role="alert">{current.label}: {current.reason}</p>}
      {blocked.length > 0 && (
        <ul className="mt-2 space-y-0.5 text-xs text-slate-500">
          {blocked.map((o) => <li key={o.name}><b>{o.label}</b> — {o.reason}</li>)}
        </ul>
      )}
      <p className="mt-2 text-xs text-slate-500">The provider is locked in when sending starts (scheduled campaigns too) and is never switched automatically.</p>
    </div>
  );
}
