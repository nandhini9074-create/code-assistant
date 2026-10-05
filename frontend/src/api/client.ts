import axios from 'axios';
import type {
  Repository,
  RepositoryListResponse,
  CreateRepositoryRequest,
  SearchRequest,
  SearchResponse,
  IngestionJobResponse,
  JobStatusResponse,
  HealthResponse,
} from '../types';

const BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000/api/v1';

export const api = axios.create({
  baseURL: BASE_URL,
  headers: { 'Content-Type': 'application/json' },
  timeout: 120_000,
});

// ── Repositories ──────────────────────────────────────────────────────────────

export const repositoryApi = {
  list: (): Promise<RepositoryListResponse> =>
    api.get<RepositoryListResponse>('/repositories/').then((r) => r.data),

  get: (id: string): Promise<Repository> =>
    api.get<Repository>(`/repositories/${id}`).then((r) => r.data),

  create: (body: CreateRepositoryRequest): Promise<Repository> =>
    api.post<Repository>('/repositories/', body).then((r) => r.data),

  delete: (id: string): Promise<void> =>
    api.delete(`/repositories/${id}`).then(() => undefined),

  uploadZip: (
    file: File,
    repoName: string,
    onProgress?: (pct: number) => void,
  ): Promise<IngestionJobResponse> => {
    const form = new FormData();
    form.append('file', file);
    form.append('repo_name', repoName);
    return api
      .post<IngestionJobResponse>('/repositories/zip', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
        onUploadProgress: (e) => {
          if (onProgress && e.total) {
            onProgress(Math.round((e.loaded * 100) / e.total));
          }
        },
      })
      .then((r) => r.data);
  },
};

// ── Search ────────────────────────────────────────────────────────────────────

export const searchApi = {
  search: (body: SearchRequest): Promise<SearchResponse> =>
    api.post<SearchResponse>('/search/', body).then((r) => r.data),
};

// ── Ingestion ─────────────────────────────────────────────────────────────────

export const ingestionApi = {
  trigger: (repoId: string, commitSha?: string): Promise<IngestionJobResponse> =>
    api
      .post<IngestionJobResponse>('/ingestion/', { repo_id: repoId, commit_sha: commitSha })
      .then((r) => r.data),

  reindex: (repoId: string, full = false): Promise<IngestionJobResponse> =>
    api
      .post<IngestionJobResponse>(`/ingestion/${repoId}/reindex?full=${full}`)
      .then((r) => r.data),

  deleteIndex: (repoId: string): Promise<void> =>
    api.delete(`/ingestion/${repoId}/index`).then(() => undefined),
};

// ── Jobs ──────────────────────────────────────────────────────────────────────

export const jobsApi = {
  listForRepo: (repoId: string): Promise<JobStatusResponse[]> =>
    api.get<JobStatusResponse[]>(`/jobs/repository/${repoId}`).then((r) => r.data),

  getStatus: (jobId: string): Promise<JobStatusResponse> =>
    api.get<JobStatusResponse>(`/jobs/${jobId}`).then((r) => r.data),

  cancel: (jobId: string): Promise<void> =>
    api.post(`/jobs/${jobId}/cancel`).then(() => undefined),
};

// ── Health ────────────────────────────────────────────────────────────────────

export const healthApi = {
  check: (): Promise<HealthResponse> =>
    api.get<HealthResponse>('/health/').then((r) => r.data),
};
