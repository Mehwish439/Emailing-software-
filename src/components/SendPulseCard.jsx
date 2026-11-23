import { useEffect, useState } from "react";

import { Async, Badge, Field, Notice, when } from "./admin/ui";
import { useToast } from "../context/ToastContext";
import useApi from "../hooks/useApi";
import { sendpulse } from "../services/adminService";
import { fieldErrors, formatApiError } from "../utils/formatError";

const STATE = {
  connected: ["ok", "Connected"], failed: ["failed", "Connection failed"],
  untested: ["pending", "Not tested yet"], not_configured: ["pending", "Not configured"],
};

/**
 * SendPulse credentials + connection status (platform admins). Everything shown comes from
 * /api/providers/sendpulse/*. Secret fields are write-only: the server never returns their values, so a
 * blank field means "keep what is stored".
 */
export default function SendPulseCard() {
  const { showToast } = useToast();
  const settings = useApi(sendpulse.settings);
  const [form, setForm] = useState({ client_id: "", client_secret: "", webhook_secret: "", sender_name: "", sender_email: "" });
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [result, setResult] = useState(null);

  useEffect(() => {
    const s = settings.data;
    if (s) setForm((f) => ({ ...f, sender_name: s.sender_name || "", sender_email: s.sender_email || "" }));
  }, [settings.data]);

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const save = async (e) => {
    e.preventDefault();
    setSaving(true); setErrors({});
    try {
      await sendpulse.saveSettings(form);
      setForm((f) => ({ ...f, client_id: "", client_secret: "", webhook_secret: "" }));
      setResult(null);
      showToast("SendPulse settings saved.", "success");
      settings.reload();
    } catch (err) {
      setErrors({ ...fieldErrors(err), form: formatApiError(err, "Could not save SendPulse settings.") });
    } finally { setSaving(false); }
  };

  const test = async () => {
    setTesting(true); setResult(null);
    try { setResult(await sendpulse.test()); settings.reload(); }
    catch (err) { setResult({ ok: false, detail: formatApiError(err, "Test failed."), checks: [], warnings: [] }); }
    finally { setTesting(false); }
  };

  const sync = async () => {
    setSyncing(true);
    try { const r = await sendpulse.sync(25); showToast(`Checked ${r.checked} message(s); ${r.events} new event(s).`, "success"); }
    catch (err) { showToast(formatApiError(err, "Sync failed."), "error"); }
    finally { setSyncing(false); }
  };

  return (
    <Async state={settings}>{(s) => {
      const [tone, label] = STATE[s.status.state] || STATE.untested;
      return (
        <form onSubmit={save} className="card p-5 space-y-4 max-w-2xl">
          <div className="flex items-center justify-between gap-2">
            <h2 className="font-semibold">SendPulse</h2>
            <Badge value={tone} label={label} />
          </div>
          {errors.form && <Notice tone="error">{errors.form}</Notice>}
          {s.config_error && <Notice tone="error">{s.config_error}</Notice>}
          {!s.encryption_available && (
            <Notice tone="warn">Credentials cannot be saved here until <code>PROVIDER_CREDENTIALS_KEY</code> is set on the server. You can instead set <code>SENDPULSE_CLIENT_ID</code> and <code>SENDPULSE_CLIENT_SECRET</code> as environment variables.</Notice>
          )}
          <p className="text-xs text-slate-500">
            {s.source === "database" && "Credentials are stored encrypted in the database."}
            {s.source === "environment" && "Credentials are coming from server environment variables. Saving here would override them."}
            {s.source === "none" && "No credentials yet."}
            {s.status.last_tested_at && <> Last tested {when(s.status.last_tested_at)}{s.status.detail ? ` — ${s.status.detail}` : ""}</>}
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <Field label="Client ID" htmlFor="sp-id" error={errors.client_id} hint={s.client_id_set ? `Saved (${s.client_id_hint}). Leave blank to keep.` : "SendPulse → Settings → API"}>
              <input id="sp-id" className="input" autoComplete="off" value={form.client_id} onChange={set("client_id")} />
            </Field>
            <Field label="Client Secret" htmlFor="sp-secret" error={errors.client_secret} hint={s.client_secret_set ? "Saved. Leave blank to keep." : "Never shown again after saving"}>
              <input id="sp-secret" type="password" className="input" autoComplete="new-password" value={form.client_secret} onChange={set("client_secret")} />
            </Field>
            <Field label="Default sender name" htmlFor="sp-sn" error={errors.sender_name}>
              <input id="sp-sn" className="input" value={form.sender_name} onChange={set("sender_name")} />
            </Field>
            <Field label="Default sender email" htmlFor="sp-se" error={errors.sender_email} hint="Must be a sender verified in SendPulse">
              <input id="sp-se" type="email" className="input" value={form.sender_email} onChange={set("sender_email")} />
            </Field>
          </div>
          <Field label="Webhook secret" htmlFor="sp-wh" error={errors.webhook_secret} hint={s.webhook_secret_set ? "Saved. Leave blank to keep." : "Choose any long random secret, save it here, and add the header X-Webhook-Secret with the same value under Additional headers on the SendPulse webhook (or use the secret key SendPulse shows). Without it, events are rejected."}>
            <input id="sp-wh" type="password" className="input" autoComplete="new-password" value={form.webhook_secret} onChange={set("webhook_secret")} />
          </Field>
          <p className="text-xs text-slate-500 break-all">Webhook URL for SendPulse (SMTP events): <code>{s.webhook_url}</code></p>
          <div className="flex flex-wrap gap-2">
            <button className="btn-primary" disabled={saving}>{saving ? "Saving…" : "Save SendPulse settings"}</button>
            <button type="button" className="btn-secondary" onClick={test} disabled={testing || !(s.client_id_set && s.client_secret_set)}>{testing ? "Testing…" : "Test connection (sends no email)"}</button>
            <button type="button" className="btn-secondary" onClick={sync} disabled={syncing || !s.client_secret_set}>{syncing ? "Syncing…" : "Sync recent statuses"}</button>
          </div>
          {result && (
            <div className="space-y-2" role="status">
              <Notice tone={result.ok ? "info" : "error"}>{result.detail}</Notice>
              {result.checks?.map((c) => <p key={c.name} className="text-xs text-slate-600">{c.ok ? "✓" : "✗"} {c.name}: {c.detail}</p>)}
              {result.warnings?.map((w, i) => <Notice key={i} tone="warn">{w}</Notice>)}
            </div>
          )}
        </form>
      );
    }}</Async>
  );
}
