/** CSS-only tooltip (shows on hover and keyboard focus). */
export default function Tooltip({ text, children, side = "top" }) {
  const pos = side === "top" ? "bottom-full mb-1.5 left-1/2 -translate-x-1/2" : "top-full mt-1.5 left-1/2 -translate-x-1/2";
  return (
    <span className="group relative inline-flex">
      {children}
      <span role="tooltip" className={`pointer-events-none absolute ${pos} z-40 whitespace-nowrap rounded-md bg-slate-900 px-2 py-1 text-xs font-medium text-white opacity-0 shadow-pop transition group-hover:opacity-100 group-focus-within:opacity-100`}>
        {text}
      </span>
    </span>
  );
}
