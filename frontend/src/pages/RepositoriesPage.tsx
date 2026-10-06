import React, { useState, useEffect, useCallback } from 'react';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Button from '@mui/material/Button';
import TextField from '@mui/material/TextField';
import Grid from '@mui/material/Grid';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Collapse from '@mui/material/Collapse';
import CircularProgress from '@mui/material/CircularProgress';
import Dialog from '@mui/material/Dialog';
import DialogTitle from '@mui/material/DialogTitle';
import DialogContent from '@mui/material/DialogContent';
import DialogContentText from '@mui/material/DialogContentText';
import DialogActions from '@mui/material/DialogActions';
import Divider from '@mui/material/Divider';
import RefreshIcon from '@mui/icons-material/Refresh';
import AddIcon from '@mui/icons-material/Add';
import AccountTreeIcon from '@mui/icons-material/AccountTree';
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
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);

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
    try {
      await repositoryApi.delete(id);
      addToast('success', 'Repository deleted');
      setRepos((prev) => prev.filter((r) => r.id !== id));
    } catch {
      addToast('error', 'Delete failed');
    } finally {
      setDeleteConfirmId(null);
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

  const repoToDelete = repos.find((r) => r.id === deleteConfirmId);

  return (
    <Box sx={{ px: { xs: 2, md: 4 }, py: { xs: 2.5, md: 3 }, maxWidth: 1500, mx: 'auto', width: '100%' }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 3, gap: 2, flexDirection: { xs: 'column', sm: 'row' } }}>
        <Box>
          <Typography variant="h4" sx={{ fontWeight: 800, mb: 1 }} gutterBottom>
            Repositories
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Manage indexed GitHub repositories
          </Typography>
        </Box>
        <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
          <Button
            id="repos-refresh"
            variant="outlined"
            size="small"
            startIcon={<RefreshIcon />}
            onClick={loadRepos}
            aria-label="Refresh repositories"
          >
            Refresh
          </Button>
          <Button
            id="repos-add"
            variant="contained"
            size="small"
            startIcon={showAdd ? undefined : <AddIcon />}
            onClick={() => setShowAdd((v) => !v)}
            aria-expanded={showAdd}
          >
            {showAdd ? 'Cancel' : 'Add Repository'}
          </Button>
        </Box>
      </Box>

      {!loading && repos.length > 0 && (
        <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mb: 3 }}>
          <Box component="span" sx={{ px: 1.5, py: 0.5, borderRadius: 999, bgcolor: 'rgba(122,92,255,0.12)', color: 'primary.light', border: '1px solid rgba(122,92,255,0.2)', fontSize: 12, fontWeight: 700 }}>
            Total {repos.length}
          </Box>
          <Box component="span" sx={{ px: 1.5, py: 0.5, borderRadius: 999, bgcolor: 'rgba(36,168,134,0.12)', color: 'success.light', border: '1px solid rgba(36,168,134,0.2)', fontSize: 12, fontWeight: 700 }}>
            Healthy {repos.filter((repo) => repo.status === 'indexed').length}
          </Box>
        </Box>
      )}

      <Collapse in={showAdd}>
        <Card sx={{ mb: 3, borderRadius: 3 }}>
          <CardContent sx={{ p: { xs: 2, md: 3 } }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2.5 }}>
              <AccountTreeIcon sx={{ color: 'primary.main' }} />
              <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                Register New Repository
              </Typography>
            </Box>
            <Box component="form" onSubmit={handleAdd}>
              <Grid container spacing={2}>
                <Grid size={{ xs: 12, sm: 6 }}>
                  <TextField
                    id="add-repo-url"
                    label="GitHub URL *"
                    fullWidth
                    placeholder="https://github.com/owner/repo"
                    value={form.repo_url}
                    onChange={(e) => setForm((f) => ({ ...f, repo_url: e.target.value }))}
                    required
                    size="small"
                  />
                </Grid>
                <Grid size={{ xs: 12, sm: 6 }}>
                  <TextField
                    id="add-repo-branch"
                    label="Branch"
                    fullWidth
                    placeholder="main"
                    value={form.branch}
                    onChange={(e) => setForm((f) => ({ ...f, branch: e.target.value }))}
                    size="small"
                  />
                </Grid>
                <Grid size={{ xs: 12 }}>
                  <TextField
                    id="add-repo-pat"
                    label="GitHub PAT (optional)"
                    fullWidth
                    type="password"
                    placeholder="ghp_xxxxxxxxxxxx"
                    value={form.pat_token}
                    onChange={(e) => setForm((f) => ({ ...f, pat_token: e.target.value }))}
                    size="small"
                  />
                </Grid>
              </Grid>

              <Divider sx={{ my: 2 }} />

              <Box sx={{ display: 'flex', gap: 1, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
                <Button type="button" id="add-repo-cancel" variant="outlined" onClick={() => setShowAdd(false)}>
                  Cancel
                </Button>
                <Button
                  type="submit"
                  id="add-repo-submit"
                  variant="contained"
                  disabled={submitting}
                  startIcon={submitting ? <CircularProgress size={16} color="inherit" /> : <AddIcon />}
                >
                  {submitting ? 'Registering…' : 'Register'}
                </Button>
              </Box>
            </Box>
          </CardContent>
        </Card>
      </Collapse>

      {loading ? (
        <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: '30vh', gap: 2 }}>
          <CircularProgress size={40} />
          <Typography variant="body2" color="text.secondary">Loading repositories…</Typography>
        </Box>
      ) : repos.length === 0 ? (
        <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: '40vh', gap: 2, textAlign: 'center' }}>
          <Box sx={{ width: 80, height: 80, borderRadius: '50%', bgcolor: 'hsla(258,90%,66%,0.1)', border: '1px solid hsla(258,90%,66%,0.2)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <AccountTreeIcon sx={{ fontSize: 36, color: 'primary.main' }} />
          </Box>
          <Box>
            <Typography variant="h6" sx={{ fontWeight: 700, mb: 1 }} gutterBottom>
              No repositories yet
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ maxWidth: 380, mb: 2 }}>
              Register a GitHub repository to start indexing and searching your code.
            </Typography>
            <Button id="repos-empty-add" variant="contained" startIcon={<AddIcon />} onClick={() => setShowAdd(true)}>
              Add First Repository
            </Button>
          </Box>
        </Box>
      ) : (
        <Grid container spacing={2}>
          {repos.map((repo) => (
            <Grid key={repo.id} size={{ xs: 12, sm: 6, lg: 4 }}>
              <RepositoryCard
                repo={repo}
                onDelete={(id) => setDeleteConfirmId(id)}
                onReindex={handleReindex}
                onViewJobs={handleViewJobs}
              />
            </Grid>
          ))}
        </Grid>
      )}

      <Dialog open={!!deleteConfirmId} onClose={() => setDeleteConfirmId(null)} maxWidth="xs" fullWidth id="delete-repo-dialog">
        <DialogTitle sx={{ fontWeight: 700 }}>Delete Repository?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            This will permanently delete <strong>{repoToDelete?.full_name}</strong> and all its indexed data. This action cannot be undone.
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button id="delete-repo-cancel" onClick={() => setDeleteConfirmId(null)} color="inherit">
            Cancel
          </Button>
          <Button id="delete-repo-confirm" onClick={() => deleteConfirmId && handleDelete(deleteConfirmId)} color="error" variant="contained">
            Delete
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default RepositoriesPage;
