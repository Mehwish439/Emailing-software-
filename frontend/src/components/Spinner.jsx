export default function Spinner({ size = "md" }) {
  const sizes = { sm: "h-4 w-4 border-2", md: "h-6 w-6 border-2", lg: "h-10 w-10 border-[3px]" };
  return (
    <div
      className={`animate-spin rounded-full border-slate-300 border-t-brand-600 ${sizes[size]}`}
      role="status"
      aria-label="Loading"
    />
  );
}
