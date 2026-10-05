import React from 'react';
import type { Repository } from '../types';
import { GitBranch, Trash2, RefreshCw, ExternalLink, Cpu } from 'lucide-react';

interface Props {
  repo: Repository;
  onDelete: (id: string) => void;
  onReindex: (id: string) => void;
  onViewJobs: (id: string) => void;
}

const statusLabels: Record<string, string> = {
  indexed:  'Indexed',
  pending:  'Pending',
  indexing: 'Indexing',
  error:    'Error',
  stale:    'Stale',
};

const RepositoryCard: React.FC<Props> = ({ repo, onDelete, onReindex, onViewJobs }) => {
  return (
    <div className="repo-card" role="article" aria-label={`Repository: ${repo.full_name}`}>
      {/* Header */}
      <div className="repo-card-name">
        <GitBranch size={15} color="var(--color-accent)" />
        {repo.name}
        <span className={`badge badge-${repo.status}`}>
          {statusLabels[repo.status] ?? repo.status}
        </span>
      </div>
      <div className="repo-card-owner">{repo.owner}</div>

      {/* Meta */}
      <div className="kv-list">
        <div className="kv-row">
          <span className="kv-key">Collection</span>
          <span className="kv-value" style={{ maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {repo.qdrant_collection}
          </span>
        </div>
        {repo.current_commit_sha && (
          <div className="kv-row">
            <span className="kv-key">Commit</span>
            <span className="kv-value">{repo.current_commit_sha.slice(0, 12)}</span>
          </div>
        )}
        <div className="kv-row">
          <span className="kv-key">Webhook</span>
          <span
            className="kv-value"
            style={{ color: repo.webhook_configured ? 'var(--color-success)' : 'var(--color-text-muted)' }}
          >
            {repo.webhook_configured ? 'Active' : 'Not set'}
          </span>
        </div>
      </div>

      {/* Actions */}
      <div className="repo-card-actions">
        <a
          href={repo.github_url}
          id={`repo-github-${repo.id}`}
          target="_blank"
          rel="noopener noreferrer"
          className="btn btn-ghost btn-sm"
          aria-label={`Open ${repo.full_name} on GitHub`}
        >
          <ExternalLink size={13} /> GitHub
        </a>
        <button
          id={`repo-jobs-${repo.id}`}
          className="btn btn-secondary btn-sm"
          onClick={() => onViewJobs(repo.id)}
          aria-label={`View jobs for ${repo.name}`}
        >
          <Cpu size={13} /> Jobs
        </button>
        <button
          id={`repo-reindex-${repo.id}`}
          className="btn btn-secondary btn-sm"
          onClick={() => onReindex(repo.id)}
          aria-label={`Reindex ${repo.name}`}
        >
          <RefreshCw size={13} /> Reindex
        </button>
        <button
          id={`repo-delete-${repo.id}`}
          className="btn btn-danger btn-sm"
          onClick={() => onDelete(repo.id)}
          aria-label={`Delete ${repo.name}`}
        >
          <Trash2 size={13} />
        </button>
      </div>
    </div>
  );
};

export default RepositoryCard;
