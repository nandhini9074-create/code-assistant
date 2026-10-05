// ── Repository ────────────────────────────────────────────────────────────────

export interface Repository {
  id: string;
  name: string;
  owner: string;
  full_name: string;
  github_url: string;
  status: RepositoryStatus;
  current_commit_sha: string | null;
  qdrant_collection: string;
  webhook_configured: boolean;
  webhook_error: string | null;
}

export type RepositoryStatus =
  | 'pending'
  | 'indexing'
  | 'indexed'
  | 'error'
  | 'stale';

export interface RepositoryListResponse {
  repositories: Repository[];
}

export interface CreateRepositoryRequest {
  repo_url: string;
  branch?: string;
  pat_token?: string;
}

// ── Search ────────────────────────────────────────────────────────────────────

export type SourceType = 'git' | 'zip';

export interface SearchSource {
  type: SourceType;
  location: string;
}

export interface SearchRequest {
  source: SearchSource;
  query: string;
}

export interface AmbiguousCandidate {
  name: string;
  file_path: string;
  class_name: string | null;
  start_line: number | null;
  end_line: number | null;
  score: number | null;
}

export interface SearchResponse {
  intent: string;
  repository: Record<string, unknown> | null;
  target: Record<string, unknown> | null;
  requirement: string | null;
  current_behavior: string | null;
  suggestion: string | null;
  proposed_change: string | null;
  code_change: Record<string, unknown> | null;
  suggested_code: string | null;
  suggested_patch: string | null;
  patch_validation: Record<string, unknown> | null;
  formatted_output: string | null;
  confidence: string | null;
  early_exit: Record<string, unknown> | null;
  ambiguous_candidates: AmbiguousCandidate[];
}

// ── Ingestion / Jobs ──────────────────────────────────────────────────────────

export interface IngestionJobResponse {
  job_id: string;
  repo_id: string;
  status: string;
  message?: string;
  stage?: string;
  processed_files?: number;
  processed_chunks?: number;
  error_info?: string | null;
}

export interface JobStatusResponse {
  job_id: string;
  repo_id: string;
  status: string;
  job_type: string;
  trigger_source: string;
  commit_sha: string | null;
  stage: string | null;
  processed_files: number;
  processed_chunks: number;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

// ── Health ────────────────────────────────────────────────────────────────────

export interface HealthResponse {
  status: 'ok' | 'degraded';
  checks: {
    postgresql: string;
    qdrant: string;
    redis: string;
  };
}

// ── UI helpers ────────────────────────────────────────────────────────────────

export interface SearchHistoryItem {
  id: string;
  query: string;
  source: SearchSource;
  timestamp: number;
  response?: SearchResponse;
}

export type ToastType = 'success' | 'error' | 'info' | 'warning';

export interface Toast {
  id: string;
  type: ToastType;
  title: string;
  message?: string;
}
