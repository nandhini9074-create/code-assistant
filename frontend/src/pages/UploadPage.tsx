import React, { useState, useRef, useCallback } from 'react';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Button from '@mui/material/Button';
import TextField from '@mui/material/TextField';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import LinearProgress from '@mui/material/LinearProgress';
import Alert from '@mui/material/Alert';
import AlertTitle from '@mui/material/AlertTitle';
import Divider from '@mui/material/Divider';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableRow from '@mui/material/TableRow';
import CircularProgress from '@mui/material/CircularProgress';
import IconButton from '@mui/material/IconButton';
import Tooltip from '@mui/material/Tooltip';
import UploadFileIcon from '@mui/icons-material/UploadFile';
import FolderZipIcon from '@mui/icons-material/FolderZip';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import CloseIcon from '@mui/icons-material/Close';
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
    <Box sx={{ px: { xs: 2, md: 4 }, py: 3, maxWidth: 680 }}>
      <Typography variant="h4" fontWeight={800} gutterBottom>
        Upload ZIP
      </Typography>
      <Typography variant="body2" color="text.secondary" mb={3}>
        Upload a local ZIP archive to index and search its code.
      </Typography>

      {/* Dropzone */}
      <Box
        id="upload-dropzone"
        role="button"
        aria-label="Drop ZIP file here or click to browse"
        tabIndex={0}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        onKeyDown={(e) => e.key === 'Enter' && inputRef.current?.click()}
        sx={{
          border: '2px dashed',
          borderColor: dragOver ? 'primary.main' : 'divider',
          borderRadius: 3,
          p: 4,
          mb: 2.5,
          cursor: 'pointer',
          textAlign: 'center',
          transition: 'all 0.2s ease',
          bgcolor: dragOver ? 'hsla(258,90%,66%,0.06)' : 'transparent',
          '&:hover': {
            borderColor: 'primary.main',
            bgcolor: 'hsla(258,90%,66%,0.04)',
          },
        }}
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
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, justifyContent: 'center' }}>
            <FolderZipIcon sx={{ fontSize: 40, color: 'primary.main' }} />
            <Box sx={{ textAlign: 'left' }}>
              <Typography variant="subtitle1" fontWeight={700}>{file.name}</Typography>
              <Typography variant="caption" color="text.secondary">
                {(file.size / 1024 / 1024).toFixed(2)} MB
              </Typography>
            </Box>
            <Tooltip title="Remove selected file">
              <IconButton
                id="upload-clear-file"
                size="small"
                onClick={(e) => { e.stopPropagation(); setFile(null); setResult(null); }}
                aria-label="Remove selected file"
                sx={{ ml: 1 }}
              >
                <CloseIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </Box>
        ) : (
          <>
            <UploadFileIcon sx={{ fontSize: 48, color: 'text.disabled', mb: 1.5 }} />
            <Typography variant="subtitle1" fontWeight={600} gutterBottom>
              Drop your ZIP file here
            </Typography>
            <Typography variant="body2" color="text.secondary">
              or click to browse — .zip files only
            </Typography>
          </>
        )}
      </Box>

      {/* Repo name input */}
      <Card sx={{ mb: 2.5 }}>
        <CardContent>
          <TextField
            id="upload-repo-name"
            label="Repository Name *"
            fullWidth
            placeholder="my-project"
            value={repoName}
            onChange={(e) => setRepoName(e.target.value)}
            size="small"
            helperText="Used as an identifier for the indexed collection. Letters, numbers, dashes only."
          />
        </CardContent>
      </Card>

      {/* Progress */}
      {uploading && (
        <Card sx={{ mb: 2.5 }}>
          <CardContent>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
              <Typography variant="body2" color="text.secondary">Uploading & indexing…</Typography>
              <Typography variant="body2" fontWeight={700}>{progress}%</Typography>
            </Box>
            <LinearProgress variant="determinate" value={progress} />
          </CardContent>
        </Card>
      )}

      {/* Result */}
      {result && (
        <Alert
          severity="success"
          icon={<CheckCircleIcon />}
          variant="outlined"
          sx={{ mb: 2.5 }}
        >
          <AlertTitle>Indexing Complete</AlertTitle>
          <Table size="small" sx={{ mt: 1, '& td': { border: 'none', py: 0.5, px: 0 } }}>
            <TableBody>
              <TableRow>
                <TableCell><Typography variant="caption" color="text.secondary">Job ID</Typography></TableCell>
                <TableCell><Typography variant="caption" sx={{ fontFamily: "'JetBrains Mono', monospace" }}>{result.job_id}</Typography></TableCell>
              </TableRow>
              <TableRow>
                <TableCell><Typography variant="caption" color="text.secondary">Repository ID</Typography></TableCell>
                <TableCell><Typography variant="caption" sx={{ fontFamily: "'JetBrains Mono', monospace" }}>{result.repo_id}</Typography></TableCell>
              </TableRow>
              <TableRow>
                <TableCell><Typography variant="caption" color="text.secondary">Status</Typography></TableCell>
                <TableCell><Typography variant="caption" sx={{ fontWeight: 700, color: 'success.main' }}>{result.status}</Typography></TableCell>
              </TableRow>
              {result.processed_files != null && (
                <TableRow>
                  <TableCell><Typography variant="caption" color="text.secondary">Files processed</Typography></TableCell>
                  <TableCell><Typography variant="caption" sx={{ fontWeight: 600 }}>{result.processed_files}</Typography></TableCell>
                </TableRow>
              )}
              {result.processed_chunks != null && (
                <TableRow>
                  <TableCell><Typography variant="caption" color="text.secondary">Chunks indexed</Typography></TableCell>
                  <TableCell><Typography variant="caption" sx={{ fontWeight: 600 }}>{result.processed_chunks}</Typography></TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </Alert>
      )}

      <Divider sx={{ mb: 2.5 }} />

      {/* Submit */}
      <Button
        id="upload-submit"
        variant="contained"
        size="large"
        fullWidth
        onClick={handleUpload}
        disabled={uploading || !file}
        aria-label="Upload and index ZIP file"
        startIcon={uploading ? <CircularProgress size={20} color="inherit" /> : <UploadFileIcon />}
      >
        {uploading ? 'Indexing…' : 'Upload & Index'}
      </Button>
    </Box>
  );
};

export default UploadPage;
