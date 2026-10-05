import React from 'react';
import { CheckCircle, AlertCircle, AlertTriangle, Info, X } from 'lucide-react';
import { useToast } from '../context/ToastContext';
import type { Toast } from '../types';

const ICONS: Record<Toast['type'], React.ReactNode> = {
  success: <CheckCircle size={16} color="var(--color-success)" />,
  error:   <AlertCircle  size={16} color="var(--color-error)" />,
  warning: <AlertTriangle size={16} color="var(--color-warning)" />,
  info:    <Info          size={16} color="var(--color-accent)" />,
};

const ToastContainer: React.FC = () => {
  const { toasts, removeToast } = useToast();

  return (
    <div className="toast-container" role="region" aria-label="Notifications">
      {toasts.map((t) => (
        <div key={t.id} className={`toast ${t.type}`} role="alert">
          <span style={{ marginTop: 1 }}>{ICONS[t.type]}</span>
          <div style={{ flex: 1 }}>
            <div className="toast-title">{t.title}</div>
            {t.message && <div className="toast-message">{t.message}</div>}
          </div>
          <button
            id={`toast-close-${t.id}`}
            className="btn btn-ghost btn-icon"
            onClick={() => removeToast(t.id)}
            aria-label="Dismiss notification"
            style={{ padding: 2 }}
          >
            <X size={14} />
          </button>
        </div>
      ))}
    </div>
  );
};

export default ToastContainer;
