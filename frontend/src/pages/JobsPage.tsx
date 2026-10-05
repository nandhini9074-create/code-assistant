import React, { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Activity, RefreshCw, XCircle, ChevronRight } from 'lucide-react';
import { jobsApi, repositoryApi } from '../api/client';
import type { JobStatusResponse, Repository } from '../types';
import { useToast } from '../context/ToastContext';

const statusColor: Record<string, string> = {
  completed: 'var(--color-success)',
  failed:    'var(--color-error)',
  running:   'var(--color-accent-2)',
  queued:    'var(--color-text-muted)',
  pending:   'var(--color-text-muted)',
  cancelled: 'var(--color-warning)',
};

const JobsPage: React.FC = () => {
  const { addToast } = useToast();
  const [params] = useSearchParams();
  const repoIdParam = params.get('repo');

  const [repos, setRepos] = useState<Repository[]>([]);
  const [selectedRepo, setSelectedRepo] = useState<string>(repoIdParam ?? '');
  const [jobs, setJobs] = useState<JobStatusResponse[]>([]);
  const [loading, setLoading] = useState(false);
  const [expandedJob, setExpandedJob] = useState<string | null>(null);

  useEffect(() => {
    repositoryApi.list().then((d) => setRepos(d.repositories)).catch(() => {});
  }, []);

  const loadJobs = useCallback(async () => {
    if (!selectedRepo) return;
    setLoading(true);
    try {
      const data = await jobsApi.listForRepo(selectedRepo);
      setJobs(data);
    } catch {
      addToast('error', 'Failed to load jobs');
    } finally {
      setLoading(false);
    }
  }, [selectedRepo, addToast]);

  useEffect(() => { loadJobs(); }, [loadJobs]);

  const handleCancel = async (jobId: string) => {
    try {
      await jobsApi.cancel(jobId);
      addToast('info', 'Cancellation requested');
      loadJobs();
    } catch {
      addToast('error', 'Cancel failed');
    }
  };

  const fmtDate = (s: string) =>
    new Date(s).toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'medium' });

  return (
    <div className="page">
      <h1 className="page-title">Ingestion Jobs</h1>
      <p className="page-sub">Monitor repository indexing job history and status.</p>

      {/* Repository selector */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 20, alignItems: 'center' }}>
        <select
          id="jobs-repo-select"
          className="form-select"
          style={{ maxWidth: 320 }}
          value={selectedRepo}
          onChange={(e) => setSelectedRepo(e.target.value)}
          aria-label="Select repository"
        >
          <option value="">— Select repository —</option>
          {repos.map((r) => (
            <option key={r.id} value={r.id}>{r.full_name}</option>
          ))}
        </select>
        <button id="jobs-refresh" className="btn btn-secondary" onClick={loadJobs} disabled={!selectedRepo} aria-label="Refresh jobs">
          <RefreshCw size={15} />
        </button>
      </div>

      {/* Jobs table */}
      {loading ? (
        <div className="loading-overlay"><div className="spinner spinner-lg" /><span>Loading jobs…</span></div>
      ) : !selectedRepo ? (
        <div className="empty-state">
          <div className="empty-state-icon"><Activity size={48} /></div>
          <div className="empty-state-title">Select a repository</div>
          <div className="empty-state-sub">Choose a repository above to view its ingestion job history.</div>
        </div>
      ) : jobs.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon"><Activity size={48} /></div>
          <div className="empty-state-title">No jobs found</div>
          <div className="empty-state-sub">No ingestion jobs have been run for this repository yet.</div>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {jobs.map((job) => {
            const expanded = expandedJob === job.job_id;
            const isActive = ['running', 'queued', 'pending'].includes(job.status.toLowerCase());
            return (
              <div
                key={job.job_id}
                className="card"
                style={{
                  padding: 0,
                  borderColor: isActive ? 'hsla(200, 90%, 60%, 0.3)' : undefined,
                }}
              >
                {/* Row header */}
                <button
                  id={`job-row-${job.job_id}`}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 12,
                    padding: '14px 20px',
                    background: 'none',
                    border: 'none',
                    cursor: 'pointer',
                    width: '100%',
                    textAlign: 'left',
                    color: 'inherit',
                  }}
                  onClick={() => setExpandedJob(expanded ? null : job.job_id)}
                  aria-expanded={expanded}
                >
                  <ChevronRight
                    size={14}
                    style={{
                      flexShrink: 0,
                      transition: 'transform 0.2s',
                      transform: expanded ? 'rotate(90deg)' : 'none',
                      color: 'var(--color-text-muted)',
                    }}
                  />
                  <span
                    style={{
                      width: 10, height: 10, borderRadius: '50%', flexShrink: 0,
                      background: statusColor[job.status.toLowerCase()] ?? 'var(--color-text-muted)',
                      boxShadow: isActive ? `0 0 6px ${statusColor[job.status.toLowerCase()]}` : 'none',
                    }}
                  />
                  <span style={{ flex: 1, fontWeight: 600, fontSize: 13 }}>
                    {job.job_type.toUpperCase()} — {job.status.toUpperCase()}
                  </span>
                  <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
                    {fmtDate(job.created_at)}
                  </span>
                  {isActive && (
                    <button
                      id={`job-cancel-${job.job_id}`}
                      className="btn btn-danger btn-sm btn-icon"
                      onClick={(e) => { e.stopPropagation(); handleCancel(job.job_id); }}
                      aria-label={`Cancel job ${job.job_id}`}
                    >
                      <XCircle size={13} />
                    </button>
                  )}
                </button>

                {/* Expanded details */}
                {expanded && (
                  <div
                    style={{
                      padding: '0 20px 16px 46px',
                      borderTop: '1px solid var(--color-border-subtle)',
                      paddingTop: 14,
                    }}
                  >
                    <div className="kv-list">
                      <div className="kv-row"><span className="kv-key">Job ID</span><span className="kv-value">{job.job_id}</span></div>
                      <div className="kv-row"><span className="kv-key">Trigger</span><span className="kv-value">{job.trigger_source}</span></div>
                      {job.commit_sha && (
                        <div className="kv-row"><span className="kv-key">Commit</span><span className="kv-value">{job.commit_sha.slice(0, 16)}</span></div>
                      )}
                      {job.stage && (
                        <div className="kv-row"><span className="kv-key">Stage</span><span className="kv-value">{job.stage}</span></div>
                      )}
                      <div className="kv-row"><span className="kv-key">Files processed</span><span className="kv-value">{job.processed_files}</span></div>
                      <div className="kv-row"><span className="kv-key">Chunks indexed</span><span className="kv-value">{job.processed_chunks}</span></div>
                      <div className="kv-row"><span className="kv-key">Updated</span><span className="kv-value">{fmtDate(job.updated_at)}</span></div>
                    </div>
                    {job.error_message && (
                      <div
                        style={{
                          marginTop: 12, padding: '10px 14px',
                          background: 'hsla(0,80%,60%,0.08)',
                          border: '1px solid hsla(0,80%,60%,0.2)',
                          borderRadius: 'var(--radius-md)',
                          fontSize: 13, color: 'var(--color-error)',
                        }}
                      >
                        {job.error_message}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default JobsPage;
