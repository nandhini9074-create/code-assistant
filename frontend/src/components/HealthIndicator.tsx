import React, { useState, useEffect, useCallback } from 'react';
import { healthApi } from '../api/client';
import type { HealthResponse } from '../types';

interface Props {
  compact?: boolean;
}

const HealthIndicator: React.FC<Props> = ({ compact = false }) => {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const data = await healthApi.check();
      setHealth(data);
    } catch {
      setHealth(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 30_000);
    return () => clearInterval(id);
  }, [refresh]);

  const status = loading ? 'unknown' : health?.status ?? 'degraded';

  if (compact) {
    return (
      <div
        style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: 'var(--color-text-muted)' }}
        title={`API: ${status}`}
      >
        <span className={`health-dot ${status}`} />
        <span>API {status}</span>
      </div>
    );
  }

  return (
    <div className="card card-sm" style={{ marginBottom: 0 }}>
      <div className="card-header" style={{ marginBottom: 12 }}>
        <span className="card-title" style={{ fontSize: 14 }}>System Health</span>
        <span className={`health-dot ${status}`} />
      </div>
      {health && (
        <div className="kv-list">
          {Object.entries(health.checks).map(([key, val]) => (
            <div className="kv-row" key={key}>
              <span className="kv-key">{key}</span>
              <span
                className="kv-value"
                style={{ color: val === 'ok' ? 'var(--color-success)' : val === 'disabled' ? 'var(--color-text-muted)' : 'var(--color-error)' }}
              >
                {val}
              </span>
            </div>
          ))}
        </div>
      )}
      {!health && !loading && (
        <p style={{ fontSize: 12, color: 'var(--color-error)' }}>Cannot reach backend</p>
      )}
    </div>
  );
};

export default HealthIndicator;
