/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        // Indigo brand scale. Every existing `brand-*` utility in the app picks this up automatically.
        brand: {
          50: "#eef2ff",
          100: "#e0e7ff",
          200: "#c7d2fe",
          300: "#a5b4fc",
          400: "#818cf8",
          500: "#6366f1",
          600: "#4f46e5",
          700: "#4338ca",
          800: "#3730a3",
          900: "#312e81",
        },
        ink: { 900: "#0f172a", 700: "#334155", 500: "#64748b", 400: "#94a3b8" },
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
      },
      boxShadow: {
        card: "0 1px 2px rgba(15,23,42,0.04), 0 1px 3px rgba(15,23,42,0.05)",
        pop: "0 10px 30px -8px rgba(15,23,42,0.18), 0 4px 10px -4px rgba(15,23,42,0.08)",
        focus: "0 0 0 3px rgba(99,102,241,0.25)",
      },
      keyframes: {
        fadeIn: { from: { opacity: 0, transform: "translateY(4px)" }, to: { opacity: 1, transform: "translateY(0)" } },
        toastIn: { from: { opacity: 0, transform: "translateX(12px)" }, to: { opacity: 1, transform: "translateX(0)" } },
        pop: { from: { opacity: 0, transform: "scale(0.97)" }, to: { opacity: 1, transform: "scale(1)" } },
        shimmer: { "100%": { transform: "translateX(100%)" } },
      },
      animation: {
        "page-in": "fadeIn 0.22s ease-out",
        "toast-in": "toastIn 0.2s ease-out",
        "pop-in": "pop 0.16s ease-out",
      },
    },
  },
  plugins: [],
};
