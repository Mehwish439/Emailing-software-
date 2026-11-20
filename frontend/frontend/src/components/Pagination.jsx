export default function Pagination({ page, numPages, onPageChange }) {
  if (numPages <= 1) return null;
  return (
    <div className="flex items-center justify-between border-t border-slate-200 px-4 py-3">
      <button className="btn-secondary" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>
        Previous
      </button>
      <span className="text-sm text-slate-500">
        Page {page} of {numPages}
      </span>
      <button className="btn-secondary" disabled={page >= numPages} onClick={() => onPageChange(page + 1)}>
        Next
      </button>
    </div>
  );
}
