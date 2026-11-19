import { createContext, useCallback, useContext, useState } from "react";

import Icon from "../components/Icon";
import { toDisplayText } from "../utils/formatError";

const ToastContext = createContext(null);

let idCounter = 0;

const STYLE = {
  success: { icon: "checkCircle", ring: "text-emerald-500" },
  error: { icon: "alert", ring: "text-red-500" },
  info: { icon: "info", ring: "text-sky-500" },
};

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);

  const dismiss = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const showToast = useCallback(
    (message, type = "success") => {
      const id = ++idCounter;
      setToasts((prev) => [...prev, { id, message: toDisplayText(message, "Something went wrong."), type }]);
      setTimeout(() => dismiss(id), type === "error" ? 6000 : 4000);
    },
    [dismiss]
  );

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      <div className="pointer-events-none fixed inset-x-4 bottom-4 z-[60] flex flex-col items-end gap-2 sm:inset-x-auto sm:right-4" aria-live="polite">
        {toasts.map((toast) => {
          const s = STYLE[toast.type] || STYLE.success;
          return (
            <div key={toast.id} role={toast.type === "error" ? "alert" : "status"}
              className="pointer-events-auto flex w-full animate-toast-in items-start gap-3 rounded-xl border border-slate-200 bg-white p-3.5 shadow-pop sm:w-auto sm:min-w-[300px] sm:max-w-sm">
              <Icon name={s.icon} className={`mt-0.5 h-5 w-5 ${s.ring}`} />
              <p className="flex-1 text-sm font-medium text-slate-800">{toast.message}</p>
              <button onClick={() => dismiss(toast.id)} className="-mr-1 -mt-0.5 rounded p-1 text-slate-400 hover:text-slate-700" aria-label="Dismiss">
                <Icon name="x" className="h-4 w-4" />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within a ToastProvider");
  return ctx;
}
