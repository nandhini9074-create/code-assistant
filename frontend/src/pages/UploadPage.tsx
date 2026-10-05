import React, { useState, useRef, useCallback } from 'react';
import { Upload, FileArchive, CheckCircle, Loader2, X } from 'lucide-react';
import { repositoryApi } from '../api/client';
import { useToast } from '../context/ToastContext';
import type { IngestionJobResponse } from '../types';

const UploadPage: React.FC = () => {
  const { addToast } = useToast();
  const inputRef = useRef<HTMLInputElement>(null);

  const [file, setFile] = useState<File | null>(null);
  const [repoName, setRepoName] = useState('');
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [result, setResult] = useState<IngestionJobResponse | null>(null);

  const handleFile = (f: File) => {
    if (!f.name.endsWith('.zip')) {
      addToast('error', 'Invalid file', 'Only .zip files are supported.');
      return;
    }
    setFile(f);
    // Pre-fill repo name from file name
    const name = f.name.replace(/\.zip$/i, '').replace(/[^a-zA-Z0-9_-]/g, '-');
    if (!repoName) setRepoName(name);
    setResult(null);
  };

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer.files[0];
    if (f) handleFile(f);
  }, [repoName]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleUpload = async () => {
    if (!file) return addToast('warning', 'No file', 'Please select a ZIP file.');
    if (!repoName.trim()) return addToast('warning', 'No name', 'Please enter a repository name.');

    setUploading(true);
    setProgress(0);
    try {
      const res = await repositoryApi.uploadZip(file, repoName.trim(), (pct) => setProgress(pct));
      setResult(res);
      addToast('success', 'Upload complete', `Indexed ${res.processed_chunks ?? 0} chunks.`);
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Upload failed';
      addToast('error', 'Upload failed', msg);
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="page">
      <h1 className="page-title">Upload ZIP</h1>
      <p className="page-sub">Upload a local ZIP archive to index and search its code.</p>

      {/* Dropzone */}
      <div
        className={`dropzone ${dragOver ? 'drag-over' : ''}`}
        style={{ marginBottom: 20 }}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
        role="button"
        id="upload-dropzone"
        aria-label="Drop ZIP file here or click to browse"
        tabIndex={0}
        onKeyDown={(e) => e.key === 'Enter' && inputRef.current?.click()}
      >
        <input
          ref={inputRef}
          type="file"
          id="upload-file-input"
          accept=".zip"
          style={{ display: 'none' }}
          onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFile(f); }}
        />

        {file ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, justifyContent: 'center' }}>
            <FileArchive size={32} color="var(--color-accent)" />
            <div style={{ textAlign: 'left' }}>
              <div style={{ fontWeight: 600, fontSize: 15 }}>{file.name}</div>
              <div style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
                {(file.size / 1024 / 1024).toFixed(2)} MB
              </div>
            </div>
            <button
              id="upload-clear-file"
              className="btn btn-ghost btn-icon btn-sm"
              onClick={(e) => { e.stopPropagation(); setFile(null); setResult(null); }}
              aria-label="Remove selected file"
            >
              <X size={14} />
            </button>
          </div>
        ) : (
          <>
            <div className="dropzone-icon"><Upload size={40} /></div>
            <div className="dropzone-title">Drop your ZIP file here</div>
            <div className="dropzone-sub">or click to browse — .zip files only</div>
          </>
        )}
      </div>

      {/* Form */}
      <div className="card" style={{ marginBottom: 20 }}>
        <div className="form-group" style={{ marginBottom: 0 }}>
          <label htmlFor="upload-repo-name" className="form-label">Repository Name *</label>
          <input
            id="upload-repo-name"
            className="form-input"
            placeholder="my-project"
            value={repoName}
            onChange={(e) => setRepoName(e.target.value)}
          />
          <div style={{ fontSize: 12, color: 'var(--color-text-muted)', marginTop: 5 }}>
            Used as an identifier for the indexed collection. Letters, numbers, dashes only.
          </div>
        </div>
      </div>

      {/* Progress */}
      {uploading && (
        <div className="card" style={{ marginBottom: 20 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, marginBottom: 8 }}>
            <span style={{ color: 'var(--color-text-secondary)' }}>Uploading & indexing…</span>
            <span>{progress}%</span>
          </div>
          <div className="progress-bar">
            <div className="progress-bar-fill" style={{ width: `${progress}%` }} />
          </div>
        </div>
      )}

      {/* Result */}
      {result && (
        <div className="card" style={{ marginBottom: 20, borderColor: 'hsla(145, 70%, 50%, 0.3)' }}>
          <div className="card-title" style={{ color: 'var(--color-success)', marginBottom: 14 }}>
            <CheckCircle size={16} /> Indexing Complete
          </div>
          <div className="kv-list">
            <div className="kv-row"><span className="kv-key">Job ID</span><span className="kv-value">{result.job_id}</span></div>
            <div className="kv-row"><span className="kv-key">Repository ID</span><span className="kv-value">{result.repo_id}</span></div>
            <div className="kv-row"><span className="kv-key">Status</span><span className="kv-value" style={{ color: 'var(--color-success)' }}>{result.status}</span></div>
            {result.processed_files != null && (
              <div className="kv-row"><span className="kv-key">Files processed</span><span className="kv-value">{result.processed_files}</span></div>
            )}
            {result.processed_chunks != null && (
              <div className="kv-row"><span className="kv-key">Chunks indexed</span><span className="kv-value">{result.processed_chunks}</span></div>
            )}
          </div>
        </div>
      )}

      {/* Submit */}
      <button
        id="upload-submit"
        className="btn btn-primary btn-lg"
        onClick={handleUpload}
        disabled={uploading || !file}
        aria-label="Upload and index ZIP file"
      >
        {uploading
          ? <><Loader2 size={16} className="animate-pulse" /> Indexing…</>
          : <><Upload size={16} /> Upload &amp; Index</>}
      </button>
    </div>
  );
};

export default UploadPage;
