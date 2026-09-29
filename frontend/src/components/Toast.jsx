import React, { createContext, useCallback, useContext, useState } from 'react';
import { Info, CheckCircle2, AlertTriangle, AlertCircle, X } from 'lucide-react';

const ToastContext = createContext(null);

const TONE_ICONS = {
  info: Info,
  success: CheckCircle2,
  warning: AlertTriangle,
  error: AlertCircle,
};

export function Toast({ title, message, tone = 'info', action, onDismiss }) {
  const Icon = TONE_ICONS[tone] || Info;

  return (
    <div className={`px-toast px-toast-${tone}`}>
      <div className="px-toast-icon">
        <Icon size={18} strokeWidth={2} />
      </div>
      <div className="px-toast-body">
        {title && <div className="px-toast-title">{title}</div>}
        {message && <div className="px-toast-message">{message}</div>}
        {action && action.label && (
          <button
            type="button"
            className="px-toast-action"
            onClick={() => {
              action.onClick?.();
              onDismiss?.();
            }}
          >
            {action.label}
          </button>
        )}
      </div>
      <button
        type="button"
        className="px-toast-close"
        onClick={onDismiss}
        aria-label="Dismiss notification"
      >
        <X size={15} strokeWidth={2} />
      </button>
    </div>
  );
}

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);

  const dismiss = useCallback((id) => {
    setToasts((prev) => prev.filter((x) => x.id !== id));
  }, []);

  const show = useCallback(
    ({ title, message, tone = 'info', action, duration }) => {
      const id =
        typeof crypto !== 'undefined' && crypto.randomUUID
          ? crypto.randomUUID()
          : `toast_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;

      // Errors persist until dismissed (duration = 0) unless explicitly overridden
      const effectiveDuration =
        duration !== undefined ? duration : tone === 'error' ? 0 : 6000;

      setToasts((prev) => [...prev, { id, title, message, tone, action }]);

      if (effectiveDuration > 0) {
        setTimeout(() => dismiss(id), effectiveDuration);
      }
      return id;
    },
    [dismiss]
  );

  return (
    <ToastContext.Provider value={{ show, dismiss }}>
      {children}
      <div className="toast-stack" role="status" aria-live="polite">
        {toasts.map((t) => (
          <Toast key={t.id} {...t} onDismiss={() => dismiss(t.id)} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    return {
      show: ({ title, message }) => console.warn('[ToastFallback]', title, message),
      dismiss: () => {},
    };
  }
  return ctx;
}

export default ToastProvider;
