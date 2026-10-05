import React, { useState, useEffect, useCallback } from 'react';
import { Plus, RefreshCw, GitBranch, Loader2 } from 'lucide-react';
import { repositoryApi, ingestionApi } from '../api/client';
import type { Repository, CreateRepositoryRequest } from '../types';
import { useToast } from '../context/ToastContext';
import RepositoryCard from '../components/RepositoryCard';
import { useNavigate } from 'react-router-dom';

const RepositoriesPage: React.FC = () => {
  const { addToast } = useToast();
  const navigate = useNavigate();

  const [repos, setRepos] = useState<Repository[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState<CreateRepositoryRequest>({ repo_url: '', branch: 'main', pat_token: '' });
  const [submitting, setSubmitting] = useState(false);

  const loadRepos = useCallback(async () => {
    setLoading(true);
    try {
      const data = await repositoryApi.list();
      setRepos(data.repositories);
    } catch {
      addToast('error', 'Failed to load repositories');
    } finally {
      setLoading(false);
    }
  }, [addToast]);

  useEffect(() => { loadRepos(); }, [loadRepos]);

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      await repositoryApi.create({
        repo_url: form.repo_url,
        branch: form.branch || 'main',
        pat_token: form.pat_token || undefined,
      });
      addToast('success', 'Repository registered', form.repo_url);
      setForm({ repo_url: '', branch: 'main', pat_token: '' });
      setShowAdd(false);
      loadRepos();
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to register';
      addToast('error', 'Registration failed', msg);
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this repository and all its indexed data?')) return;
    try {
      await repositoryApi.delete(id);
      addToast('success', 'Repository deleted');
      setRepos((prev) => prev.filter((r) => r.id !== id));
    } catch {
      addToast('error', 'Delete failed');
    }
  };

  const handleReindex = async (id: string) => {
    try {
      await ingestionApi.reindex(id, true);
      addToast('info', 'Reindex queued', 'The reindex job has been queued.');
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to queue';
      addToast('error', 'Reindex failed', msg);
    }
  };

  const handleViewJobs = (id: string) => navigate(`/jobs?repo=${id}`);

  return (
    <div className="page">
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24 }}>
        <div>
          <h1 className="page-title">Repositories</h1>
          <p className="page-sub" style={{ marginBottom: 0 }}>
            Manage indexed GitHub repositories
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button id="repos-refresh" className="btn btn-secondary" onClick={loadRepos} aria-label="Refresh repositories">
            <RefreshCw size={15} />
          </button>
          <button
            id="repos-add"
            className="btn btn-primary"
            onClick={() => setShowAdd((v) => !v)}
            aria-expanded={showAdd}
          >
            <Plus size={15} /> Add Repository
          </button>
        </div>
      </div>

      {/* Add repo form */}
      {showAdd && (
        <div className="card" style={{ marginBottom: 24, animation: 'slideInUp 0.2s ease' }}>
          <div className="card-title" style={{ marginBottom: 16 }}>
            <GitBranch size={16} color="var(--color-accent)" /> Register New Repository
          </div>
          <form onSubmit={handleAdd}>
            <div className="grid-2">
              <div className="form-group">
                <label htmlFor="add-repo-url" className="form-label">GitHub URL *</label>
                <input
                  id="add-repo-url"
                  className="form-input"
                  placeholder="https://github.com/owner/repo"
                  value={form.repo_url}
                  onChange={(e) => setForm((f) => ({ ...f, repo_url: e.target.value }))}
                  required
                />
              </div>
              <div className="form-group">
                <label htmlFor="add-repo-branch" className="form-label">Branch</label>
                <input
                  id="add-repo-branch"
                  className="form-input"
                  placeholder="main"
                  value={form.branch}
                  onChange={(e) => setForm((f) => ({ ...f, branch: e.target.value }))}
                />
              </div>
            </div>
            <div className="form-group">
              <label htmlFor="add-repo-pat" className="form-label">GitHub PAT (optional)</label>
              <input
                id="add-repo-pat"
                className="form-input"
                type="password"
                placeholder="ghp_xxxxxxxxxxxx"
                value={form.pat_token}
                onChange={(e) => setForm((f) => ({ ...f, pat_token: e.target.value }))}
              />
            </div>
            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
              <button
                type="button"
                id="add-repo-cancel"
                className="btn btn-secondary"
                onClick={() => setShowAdd(false)}
              >
                Cancel
              </button>
              <button
                type="submit"
                id="add-repo-submit"
                className="btn btn-primary"
                disabled={submitting}
              >
                {submitting ? <Loader2 size={14} className="animate-pulse" /> : <Plus size={14} />}
                {submitting ? 'Registering…' : 'Register'}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Content */}
      {loading ? (
        <div className="loading-overlay">
          <div className="spinner spinner-lg" />
          <span>Loading repositories…</span>
        </div>
      ) : repos.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon"><GitBranch size={48} /></div>
          <div className="empty-state-title">No repositories yet</div>
          <div className="empty-state-sub">
            Register a GitHub repository to start indexing and searching your code.
          </div>
          <button id="repos-empty-add" className="btn btn-primary" onClick={() => setShowAdd(true)}>
            <Plus size={15} /> Add First Repository
          </button>
        </div>
      ) : (
        <div className="repo-grid">
          {repos.map((repo) => (
            <RepositoryCard
              key={repo.id}
              repo={repo}
              onDelete={handleDelete}
              onReindex={handleReindex}
              onViewJobs={handleViewJobs}
            />
          ))}
        </div>
      )}
    </div>
  );
};

export default RepositoriesPage;
