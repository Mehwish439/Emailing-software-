import { useEffect, useRef, useState } from "react";

/**
 * Small action menu. `trigger` receives ({open, toggle}). `items`: [{ label, onClick, to?, icon?, danger?, hidden? }].
 * Closes on outside click and Escape.
 */
export default function Dropdown({ trigger, children, align = "right", width = "w-56" }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const away = (e) => !ref.current?.contains(e.target) && setOpen(false);
    const esc = (e) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", away); document.removeEventListener("keydown", esc); };
  }, [open]);
  return (
    <div className="relative" ref={ref}>
      {trigger({ open, toggle: () => setOpen((o) => !o) })}
      {open && (
        <div role="menu" onClick={() => setOpen(false)}
          className={`absolute z-30 mt-2 ${width} ${align === "right" ? "right-0" : "left-0"} origin-top animate-pop-in rounded-xl border border-slate-200 bg-white p-1.5 shadow-pop`}>
          {children}
        </div>
      )}
    </div>
  );
}

export function MenuItem({ children, onClick, danger = false, as: As = "button", ...rest }) {
  return (
    <As role="menuitem" onClick={onClick} {...rest}
      className={`flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm transition ${danger ? "text-red-600 hover:bg-red-50" : "text-slate-700 hover:bg-slate-100"}`}>
      {children}
    </As>
  );
}
