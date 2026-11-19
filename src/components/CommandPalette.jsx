import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import Icon from "./Icon";

/** Ctrl/⌘+K quick navigation over the pages the signed-in user can actually open. */
export default function CommandPalette({ open, onClose, entries }) {
  const [q, setQ] = useState("");
  const [idx, setIdx] = useState(0);
  const navigate = useNavigate();
  const inputRef = useRef(null);

  useEffect(() => { if (open) { setQ(""); setIdx(0); setTimeout(() => inputRef.current?.focus(), 0); } }, [open]);

  const results = useMemo(() => {
    const s = q.trim().toLowerCase();
    return s ? entries.filter((e) => e.label.toLowerCase().includes(s) || (e.group || "").toLowerCase().includes(s)) : entries;
  }, [q, entries]);

  useEffect(() => { setIdx(0); }, [q]);

  if (!open) return null;
  const go = (e) => { if (e) { navigate(e.to); onClose(); } };
  const onKey = (e) => {
    if (e.key === "Escape") onClose();
    else if (e.key === "ArrowDown") { e.preventDefault(); setIdx((i) => Math.min(i + 1, results.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setIdx((i) => Math.max(i - 1, 0)); }
    else if (e.key === "Enter") go(results[idx]);
  };

  return (
    <div className="fixed inset-0 z-[55] flex items-start justify-center p-4 pt-[12vh]" role="dialog" aria-modal="true" aria-label="Quick navigation">
      <div className="absolute inset-0 bg-slate-900/40 backdrop-blur-[2px]" onClick={onClose} />
      <div className="relative w-full max-w-lg animate-pop-in overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-pop" onKeyDown={onKey}>
        <div className="flex items-center gap-3 border-b border-slate-100 px-4">
          <Icon name="search" className="h-4 w-4 text-slate-400" />
          <input ref={inputRef} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Go to a page…" aria-label="Go to a page"
            className="h-12 flex-1 bg-transparent text-sm outline-none placeholder:text-slate-400" />
          <kbd className="rounded border border-slate-200 px-1.5 py-0.5 text-[10px] font-medium text-slate-400">Esc</kbd>
        </div>
        <ul className="max-h-80 overflow-y-auto p-2 scroll-thin" role="listbox">
          {results.length === 0 && <li className="px-3 py-8 text-center text-sm text-slate-500">No pages match “{q}”.</li>}
          {results.map((r, i) => (
            <li key={r.to + r.label} role="option" aria-selected={i === idx}>
              <button onClick={() => go(r)} onMouseEnter={() => setIdx(i)}
                className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm ${i === idx ? "bg-brand-50 text-brand-700" : "text-slate-700"}`}>
                <Icon name={r.icon} className="h-4 w-4" />
                <span className="flex-1 font-medium">{r.label}</span>
                {r.group && <span className="text-xs text-slate-400">{r.group}</span>}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
