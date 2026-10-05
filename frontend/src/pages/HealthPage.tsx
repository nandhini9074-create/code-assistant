import React from 'react';
import HealthIndicator from '../components/HealthIndicator';
import { Zap } from 'lucide-react';

const HealthPage: React.FC = () => {
  return (
    <div className="page">
      <h1 className="page-title">System Health</h1>
      <p className="page-sub">Live status of all backend services.</p>

      <div style={{ maxWidth: 480 }}>
        <div className="card" style={{ marginBottom: 0 }}>
          <div className="card-title" style={{ marginBottom: 20 }}>
            <Zap size={16} color="var(--color-accent)" /> Service Status
          </div>
          <HealthIndicator />
        </div>
      </div>
    </div>
  );
};

export default HealthPage;
