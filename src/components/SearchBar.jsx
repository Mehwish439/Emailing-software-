import Icon from "./Icon";

export default function SearchBar({ value, onChange, placeholder = "Search…", className = "max-w-xs" }) {
  return (
    <div className={`relative w-full ${className}`}>
      <Icon name="search" className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
      <input type="search" aria-label={placeholder} className="input pl-9" placeholder={placeholder} value={value} onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}
