import Icon from "./Icon";

function pageList(page, total) {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
  const set = new Set([1, total, page, page - 1, page + 1]);
  const pages = [...set].filter((p) => p >= 1 && p <= total).sort((a, b) => a - b);
  const out = [];
  pages.forEach((p, i) => { if (i && p - pages[i - 1] > 1) out.push("…"); out.push(p); });
  return out;
}

export default function Pagination({ page, numPages, onPageChange }) {
  if (numPages <= 1) return null;
  return (
    <nav className="flex items-center justify-between gap-3 border-t border-slate-100 px-4 py-3" aria-label="Pagination">
      <p className="hidden text-sm text-slate-500 sm:block">Page {page} of {numPages}</p>
      <div className="flex w-full items-center justify-between gap-1 sm:w-auto sm:justify-end">
        <button className="btn-secondary btn-sm" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>
          <Icon name="chevronLeft" className="h-3.5 w-3.5" /> Previous
        </button>
        <div className="hidden items-center gap-1 px-1 sm:flex">
          {pageList(page, numPages).map((p, i) => p === "…"
            ? <span key={`e${i}`} className="px-1 text-slate-400">…</span>
            : <button key={p} onClick={() => onPageChange(p)} aria-current={p === page ? "page" : undefined}
                className={`h-8 min-w-8 rounded-lg px-2 text-sm font-medium transition ${p === page ? "bg-brand-600 text-white" : "text-slate-600 hover:bg-slate-100"}`}>{p}</button>)}
        </div>
        <button className="btn-secondary btn-sm" disabled={page >= numPages} onClick={() => onPageChange(page + 1)}>
          Next <Icon name="chevronRight" className="h-3.5 w-3.5" />
        </button>
      </div>
    </nav>
  );
}
