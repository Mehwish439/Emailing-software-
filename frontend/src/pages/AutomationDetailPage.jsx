// NEW FILE (Marketing Automation feature)
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import ConfirmDialog from "../components/ConfirmDialog";
import EmptyState from "../components/EmptyState";
import Modal from "../components/Modal";
import Pagination from "../components/Pagination";
import Spinner from "../components/Spinner";
import StatCard from "../components/StatCard";
import StatusBadge from "../components/StatusBadge";
import { useToast } from "../context/ToastContext";
import {
  activateAutomation,
  deleteAutomation,
  enrollContacts,
  getAutomation,
  getAutomationEnrollments,
  getAutomationLogs,
  getAutomationStats,
  pauseAutomation,
  resumeAutomation,
} from "../services/automationService";
import { listContacts } from "../services/contactService";
import { actionLabel, apiErrorMessage, formatDate, formatDelay, triggerLabel } from "../utils/automation";

function WorkflowDiagram({ automation }) {
  const cfg = automation.trigger_config || {};
  const triggerDetail =
    automation.trigger_type === "signup_form_submitted" && cfg.signup_form_id
      ? `Form #${cfg.signup_form_id}`
      : automation.trigger_type === "contact_added" && cfg.list_id
      ? `List #${cfg.list_id}`
      : null;

  const Arrow = () => <div className="text-slate-300 text-lg leading-none py-1">↓</div>;

  return (
    <div className="flex flex-col items-center text-center">
      <div className="rounded-lg border border-brand-200 bg-brand-50 px-4 py-2 text-sm font-medium text-brand-700">
        {triggerLabel(automation.trigger_type)}
        {triggerDetail && <span className="block text-xs font-normal text-brand-600">{triggerDetail}</span>}
      </div>
      {automation.steps.map((step) => (
        <div key={step.id} className="flex flex-col items-center">
          <Arrow />
          {Number(step.delay_value) > 0 && step.action_type !== "wait" && (
            <>
              <div className="rounded-full bg-amber-50 border border-amber-200 px-3 py-0.5 text-xs text-amber-800">
                Wait {step.delay_value} {step.delay_unit}
              </div>
              <Arrow />
            </>
          )}
          <div className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm shadow-sm min-w-[220px]">
            {step.action_type === "send_email" && (
              <>
                <span className="font-medium text-slate-900">{step.email_template_name || "Email"}</span>
                <span className="block text-xs text-slate-500">Send email · {formatDelay(step)}</span>
                {step.configuration?.condition && (
                  <span className="block text-xs text-indigo-600">
                    Only if contact {step.configuration.condition.negate ? "does not have" : "has"} a tag
                  </span>
                )}
              </>
            )}
            {step.action_type === "wait" && (
              <span className="font-medium text-amber-800">
                Wait {step.delay_value} {step.delay_unit}
              </span>
            )}
            {step.action_type === "end_automation" && <span className="font-medium text-slate-700">End automation</span>}
          </div>
        </div>
      ))}
      <Arrow />
      <div className="rounded-full bg-emerald-50 border border-emerald-200 px-3 py-1 text-xs font-medium text-emerald-700">Completed</div>
    </div>
  );
}

function EnrollModal({ open, onClose, onEnroll }) {
  const [search, setSearch] = useState("");
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);

  useEffect(() => {
    if (!open) return undefined;
    const timer = setTimeout(async () => {
      setSearching(true);
      try {
        const data = await listContacts({ search, page_size: 10 });
        setResults(data.results || data || []);
      } finally {
        setSearching(false);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [open, search]);

  return (
    <Modal open={open} onClose={onClose} title="Enroll a contact">
      <input className="input" placeholder="Search contacts by name or email…" value={search} onChange={(e) => setSearch(e.target.value)} />
      <div className="mt-3 divide-y divide-slate-100 max-h-72 overflow-y-auto">
        {searching ? (
          <div className="flex justify-center py-6">
            <Spinner />
          </div>
        ) : results.length === 0 ? (
          <p className="py-6 text-center text-sm text-slate-500">No contacts found.</p>
        ) : (
          results.map((c) => (
            <div key={c.id} className="flex items-center justify-between py-2">
              <div>
                <p className="text-sm font-medium text-slate-900">{c.email}</p>
                <p className="text-xs text-slate-500">{[c.first_name, c.last_name].filter(Boolean).join(" ")}</p>
              </div>
              <button className="btn-secondary" onClick={() => onEnroll(c)}>
                Enroll
              </button>
            </div>
          ))
        )}
      </div>
    </Modal>
  );
}

export default function AutomationDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { showToast } = useToast();

  const [automation, setAutomation] = useState(null);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState("overview");
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [enrollOpen, setEnrollOpen] = useState(false);

  const [enrollments, setEnrollments] = useState({ results: [], num_pages: 1 });
  const [enrollPage, setEnrollPage] = useState(1);
  const [logs, setLogs] = useState({ results: [], num_pages: 1 });
  const [logPage, setLogPage] = useState(1);

  const loadCore = useCallback(async () => {
    try {
      const [a, s] = await Promise.all([getAutomation(id), getAutomationStats(id)]);
      setAutomation(a);
      setStats(s);
    } catch (err) {
      showToast(apiErrorMessage(err, "Failed to load automation."), "error");
      navigate("/automations");
    } finally {
      setLoading(false);
    }
  }, [id, navigate, showToast]);

  useEffect(() => {
    loadCore();
  }, [loadCore]);

  useEffect(() => {
    if (tab !== "contacts") return;
    getAutomationEnrollments(id, { page: enrollPage }).then(setEnrollments).catch(() => {});
  }, [tab, enrollPage, id]);

  useEffect(() => {
    if (tab !== "activity") return;
    getAutomationLogs(id, { page: logPage }).then(setLogs).catch(() => {});
  }, [tab, logPage, id]);

  const run = async (fn, message) => {
    setBusy(true);
    try {
      await fn(id);
      showToast(message, "success");
      await loadCore();
    } catch (err) {
      showToast(apiErrorMessage(err, "Action failed."), "error");
    } finally {
      setBusy(false);
    }
  };

  const handleEnroll = async (contact) => {
    try {
      const res = await enrollContacts(id, [contact.id]);
      if (res.enrolled) showToast(`${contact.email} enrolled.`, "success");
      else showToast(`Not enrolled: ${res.skipped?.[0]?.reason || "unknown reason"}`, "info");
      setEnrollOpen(false);
      loadCore();
    } catch (err) {
      showToast(apiErrorMessage(err, "Failed to enroll contact."), "error");
    }
  };

  const handleDelete = async () => {
    try {
      await deleteAutomation(id);
      showToast("Automation deleted.", "success");
      navigate("/automations");
    } catch (err) {
      showToast(apiErrorMessage(err, "Failed to delete automation."), "error");
    }
  };

  if (loading || !automation) {
    return (
      <div className="flex justify-center py-24">
        <Spinner size="lg" />
      </div>
    );
  }

  const tabs = [
    { key: "overview", label: "Overview" },
    { key: "contacts", label: "Enrolled Contacts" },
    { key: "activity", label: "Execution History" },
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <Link to="/automations" className="text-sm text-brand-600 hover:underline">
            ← Automations
          </Link>
          <h1 className="mt-1 text-2xl font-semibold text-slate-900 flex items-center gap-3">
            {automation.name}
            <StatusBadge status={automation.status} />
          </h1>
          <p className="text-sm text-slate-500">
            Trigger: {triggerLabel(automation.trigger_type)}
            {automation.description ? ` · ${automation.description}` : ""}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {automation.status === "active" && (
            <button className="btn-secondary" disabled={busy} onClick={() => setEnrollOpen(true)}>
              Enroll contact
            </button>
          )}
          <Link to={`/automations/${id}/edit`} className="btn-secondary">
            Edit
          </Link>
          {automation.status === "draft" && (
            <button className="btn-primary" disabled={busy} onClick={() => run(activateAutomation, "Automation activated.")}>
              Activate
            </button>
          )}
          {automation.status === "active" && (
            <button className="btn-secondary" disabled={busy} onClick={() => run(pauseAutomation, "Automation paused.")}>
              Pause
            </button>
          )}
          {automation.status === "paused" && (
            <button className="btn-primary" disabled={busy} onClick={() => run(resumeAutomation, "Automation resumed.")}>
              Resume
            </button>
          )}
          <button className="btn-danger" disabled={busy} onClick={() => setConfirmDelete(true)}>
            Delete
          </button>
        </div>
      </div>

      <div className="border-b border-slate-200 flex gap-6">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`pb-3 text-sm font-medium border-b-2 -mb-px ${
              tab === t.key ? "border-brand-600 text-brand-700" : "border-transparent text-slate-500 hover:text-slate-800"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "overview" && stats && (
        <div className="space-y-6">
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
            <StatCard label="Enrolled" value={stats.enrolled} />
            <StatCard label="Active" value={stats.active + stats.paused} />
            <StatCard label="Completed" value={stats.completed} accent="text-emerald-600" />
            <StatCard label="Failed" value={stats.failed} accent="text-red-600" />
            <StatCard label="Emails sent" value={stats.emails_sent} />
            <StatCard label="Emails failed" value={stats.emails_failed} accent="text-red-600" />
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="card p-6">
              <h2 className="text-sm font-semibold text-slate-900 mb-4">Workflow</h2>
              <WorkflowDiagram automation={automation} />
            </div>
            <div className="card p-6">
              <h2 className="text-sm font-semibold text-slate-900 mb-4">Steps</h2>
              <table className="min-w-full text-sm">
                <thead>
                  <tr className="text-left text-xs uppercase text-slate-500">
                    <th className="pb-2">#</th>
                    <th className="pb-2">Step</th>
                    <th className="pb-2">Sent</th>
                    <th className="pb-2">Failed</th>
                    <th className="pb-2">Skipped</th>
                    <th className="pb-2">Waiting</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {stats.steps.map((s) => (
                    <tr key={s.step_order}>
                      <td className="py-2 text-slate-500">{s.step_order}</td>
                      <td className="py-2 text-slate-900">{s.template_name || actionLabel(s.action_type)}</td>
                      <td className="py-2">{s.success}</td>
                      <td className="py-2">{s.failed}</td>
                      <td className="py-2">{s.skipped}</td>
                      <td className="py-2">{s.waiting}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-4 text-xs text-slate-500">
                From Brevo events: {stats.emails_delivered} delivered · {stats.emails_opened} opened · {stats.emails_clicked} clicked. These
                only count once Brevo's webhook reports them.
              </p>
            </div>
          </div>
        </div>
      )}

      {tab === "contacts" && (
        <div className="card">
          {enrollments.results.length === 0 ? (
            <EmptyState title="No contacts enrolled yet" description="Contacts appear here as soon as the trigger fires." />
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-200">
                <thead className="bg-slate-50">
                  <tr>
                    {["Contact", "Status", "Next step", "Next run", "Started", "Last error"].map((h) => (
                      <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {enrollments.results.map((e) => (
                    <tr key={e.id}>
                      <td className="px-4 py-3 text-sm text-slate-900">{e.contact_email}</td>
                      <td className="px-4 py-3">
                        <StatusBadge status={e.status} />
                      </td>
                      <td className="px-4 py-3 text-sm text-slate-600">{e.status === "completed" ? "—" : `Step ${e.current_step_order}`}</td>
                      <td className="px-4 py-3 text-sm text-slate-600">{formatDate(e.next_run_at)}</td>
                      <td className="px-4 py-3 text-sm text-slate-600">{formatDate(e.started_at)}</td>
                      <td className="px-4 py-3 text-sm text-red-600 max-w-xs truncate" title={e.last_error}>
                        {e.last_error || "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <Pagination page={enrollPage} numPages={enrollments.num_pages || 1} onPageChange={setEnrollPage} />
        </div>
      )}

      {tab === "activity" && (
        <div className="card">
          {logs.results.length === 0 ? (
            <EmptyState title="Nothing has run yet" description="Each email, wait and skip is recorded here." />
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-200">
                <thead className="bg-slate-50">
                  <tr>
                    {["When", "Contact", "Step", "Action", "Status", "Details"].map((h) => (
                      <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {logs.results.map((l) => (
                    <tr key={l.id}>
                      <td className="px-4 py-3 text-sm text-slate-600 whitespace-nowrap">{formatDate(l.executed_at || l.created_at)}</td>
                      <td className="px-4 py-3 text-sm text-slate-900">{l.contact_email}</td>
                      <td className="px-4 py-3 text-sm text-slate-600">
                        {l.step_order}
                        {l.attempt > 1 ? ` (try ${l.attempt})` : ""}
                      </td>
                      <td className="px-4 py-3 text-sm text-slate-600">
                        {actionLabel(l.action_type)}
                        {l.template_name ? ` · ${l.template_name}` : ""}
                      </td>
                      <td className="px-4 py-3">
                        <StatusBadge status={l.status} />
                      </td>
                      <td className="px-4 py-3 text-sm text-slate-500 max-w-xs truncate" title={l.error_message}>
                        {l.error_message || (l.opened_at ? "Opened" : l.delivered_at ? "Delivered" : "")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <Pagination page={logPage} numPages={logs.num_pages || 1} onPageChange={setLogPage} />
        </div>
      )}

      <EnrollModal open={enrollOpen} onClose={() => setEnrollOpen(false)} onEnroll={handleEnroll} />
      <ConfirmDialog
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        onConfirm={handleDelete}
        title="Delete automation?"
        message="This permanently deletes the automation, its enrolled contacts and its history."
        confirmLabel="Delete"
      />
    </div>
  );
}
