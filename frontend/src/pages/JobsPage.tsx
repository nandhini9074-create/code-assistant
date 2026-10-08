import React, { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Button from '@mui/material/Button';
import FormControl from '@mui/material/FormControl';
import InputLabel from '@mui/material/InputLabel';
import Select from '@mui/material/Select';
import MenuItem from '@mui/material/MenuItem';
import Chip from '@mui/material/Chip';
import CircularProgress from '@mui/material/CircularProgress';
import Collapse from '@mui/material/Collapse';
import Card from '@mui/material/Card';
import Alert from '@mui/material/Alert';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableRow from '@mui/material/TableRow';
import IconButton from '@mui/material/IconButton';
import Tooltip from '@mui/material/Tooltip';
import Divider from '@mui/material/Divider';
import RefreshIcon from '@mui/icons-material/Refresh';
import WorkHistoryIcon from '@mui/icons-material/WorkHistory';
import CancelIcon from '@mui/icons-material/Cancel';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import FiberManualRecordIcon from '@mui/icons-material/FiberManualRecord';
import { jobsApi, repositoryApi } from '../api/client';
import type { JobStatusResponse, Repository } from '../types';
import { useToast } from '../context/ToastContext';

const statusConfig: Record<string, { color: 'success' | 'error' | 'info' | 'warning' | 'default'; label: string }> = {
  completed: { color: 'success', label: 'Completed' },
  failed: { color: 'error', label: 'Failed' },
  running: { color: 'info', label: 'Running' },
  queued: { color: 'default', label: 'Queued' },
  pending: { color: 'default', label: 'Pending' },
  cancelled: { color: 'warning', label: 'Cancelled' },
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

  const fmtDate = (s: string) => new Date(s).toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'medium' });

  return (
    <Box sx={{ px: { xs: 2, md: 4 }, py: { xs: 2.5, md: 3 }, maxWidth: 1500, mx: 'auto', width: '100%' }}>
      <Typography variant="h4" sx={{ fontWeight: 800, mb: 1 }} gutterBottom>
        Ingestion Jobs
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        Monitor repository indexing job history and status.
      </Typography>

      <Box sx={{ display: 'flex', gap: 1.5, mb: 3, alignItems: 'center', flexDirection: { xs: 'column', sm: 'row' } }}>
        <FormControl size="small" sx={{ minWidth: { xs: '100%', sm: 320 } }}>
          <InputLabel id="jobs-repo-label">Select repository</InputLabel>
          <Select
            id="jobs-repo-select"
            labelId="jobs-repo-label"
            label="Select repository"
            value={selectedRepo}
            onChange={(e) => setSelectedRepo(e.target.value)}
            aria-label="Select repository"
          >
            <MenuItem value=""><em>— Select repository —</em></MenuItem>
            {repos.map((r) => (
              <MenuItem key={r.id} value={r.id}>{r.full_name}</MenuItem>
            ))}
          </Select>
        </FormControl>
        <Tooltip title="Refresh jobs">
          <span>
            <IconButton id="jobs-refresh" onClick={loadJobs} disabled={!selectedRepo} aria-label="Refresh jobs">
              <RefreshIcon />
            </IconButton>
          </span>
        </Tooltip>
      </Box>

      {loading ? (
        <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: '30vh', gap: 2 }}>
          <CircularProgress size={40} />
          <Typography variant="body2" color="text.secondary">Loading jobs…</Typography>
        </Box>
      ) : !selectedRepo ? (
        <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: '40vh', gap: 2, textAlign: 'center' }}>
          <Box sx={{ width: 80, height: 80, borderRadius: '50%', bgcolor: 'hsla(258,90%,66%,0.1)', border: '1px solid hsla(258,90%,66%,0.2)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <WorkHistoryIcon sx={{ fontSize: 36, color: 'primary.main' }} />
          </Box>
          <Box>
            <Typography variant="h6" sx={{ fontWeight: 700, mb: 1 }} gutterBottom>Select a repository</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ maxWidth: 380 }}>
              Choose a repository above to view its ingestion job history.
            </Typography>
          </Box>
        </Box>
      ) : jobs.length === 0 ? (
        <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: '30vh', gap: 2, textAlign: 'center' }}>
          <Typography variant="h6" sx={{ fontWeight: 700, mb: 1 }} gutterBottom>No jobs found</Typography>
          <Typography variant="body2" color="text.secondary">
            No ingestion jobs have been run for this repository yet.
          </Typography>
          <Button variant="outlined" startIcon={<RefreshIcon />} onClick={loadJobs}>
            Refresh
          </Button>
        </Box>
      ) : (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.25 }}>
          {jobs.map((job) => {
            const expanded = expandedJob === job.job_id;
            const isActive = ['running', 'queued', 'pending'].includes(job.status.toLowerCase());
            const sc = statusConfig[job.status.toLowerCase()] ?? { color: 'default', label: job.status };

            return (
              <Card
                key={job.job_id}
                variant="outlined"
                sx={{
                  borderColor: isActive ? 'hsla(200,90%,60%,0.35)' : 'divider',
                  bgcolor: isActive ? 'hsla(200,90%,60%,0.04)' : 'transparent',
                  transition: 'all 0.2s ease',
                }}
              >
                <Box
                  component="button"
                  id={`job-row-${job.job_id}`}
                  sx={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 1.5,
                    p: '14px 16px',
                    bgcolor: 'transparent',
                    border: 'none',
                    cursor: 'pointer',
                    width: '100%',
                    textAlign: 'left',
                    color: 'inherit',
                    '&:hover': { bgcolor: 'hsla(258,90%,66%,0.04)' },
                  }}
                  onClick={() => setExpandedJob(expanded ? null : job.job_id)}
                  aria-expanded={expanded}
                >
                  {expanded ? (
                    <ExpandLessIcon sx={{ fontSize: 18, color: 'text.secondary', flexShrink: 0 }} />
                  ) : (
                    <ExpandMoreIcon sx={{ fontSize: 18, color: 'text.secondary', flexShrink: 0 }} />
                  )}

                  <FiberManualRecordIcon
                    sx={{
                      fontSize: 10,
                      flexShrink: 0,
                      color:
                        sc.color === 'success'
                          ? 'success.main'
                          : sc.color === 'error'
                            ? 'error.main'
                            : sc.color === 'info'
                              ? 'info.main'
                              : sc.color === 'warning'
                                ? 'warning.main'
                                : 'text.disabled',
                      boxShadow: isActive ? '0 0 6px currentColor' : 'none',
                    }}
                  />

                  <Typography variant="body2" sx={{ fontWeight: 600, flex: 1 }}>
                    {job.job_type.toUpperCase()}
                  </Typography>

                  <Chip
                    label={sc.label.toUpperCase()}
                    color={sc.color}
                    size="small"
                    variant={isActive ? 'filled' : 'outlined'}
                    sx={{ fontWeight: 700, fontSize: 10, letterSpacing: '0.04em' }}
                  />

                  <Typography variant="caption" color="text.secondary" sx={{ flexShrink: 0, ml: 1 }}>
                    {fmtDate(job.created_at)}
                  </Typography>

                  {isActive && (
                    <Tooltip title="Cancel job">
                      <IconButton
                        id={`job-cancel-${job.job_id}`}
                        size="small"
                        color="error"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleCancel(job.job_id);
                        }}
                        aria-label={`Cancel job ${job.job_id}`}
                      >
                        <CancelIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  )}
                </Box>

                <Collapse in={expanded}>
                  <Divider />
                  <Box sx={{ px: 3, py: 2 }}>
                    <Table size="small" sx={{ mb: job.error_message ? 2 : 0, '& td': { border: 'none', py: 0.6, px: 0 } }}>
                      <TableBody>
                        {[
                          ['Job ID', job.job_id],
                          ['Trigger', job.trigger_source],
                          job.commit_sha ? ['Commit', job.commit_sha.slice(0, 16)] : null,
                          job.stage ? ['Stage', job.stage] : null,
                          ['Files processed', job.processed_files],
                          ['Chunks indexed', job.processed_chunks],
                          ['Updated', fmtDate(job.updated_at)],
                        ]
                          .filter(Boolean)
                          .map((row) => (
                            <TableRow key={String(row![0])}>
                              <TableCell sx={{ width: 160 }}>
                                <Typography variant="caption" color="text.secondary">{String(row![0])}</Typography>
                              </TableCell>
                              <TableCell>
                                <Typography
                                  variant="caption"
                                  sx={{
                                    fontFamily: String(row![0]) === 'Job ID' || String(row![0]) === 'Commit' ? "'JetBrains Mono', monospace" : undefined,
                                    fontWeight: String(row![0]) === 'Stage' ? 600 : 400,
                                  }}
                                >
                                  {String(row![1])}
                                </Typography>
                              </TableCell>
                            </TableRow>
                          ))}
                      </TableBody>
                    </Table>

                    {job.error_message && (
                      <Alert severity="error" variant="outlined" sx={{ fontSize: 13 }}>
                        {job.error_message}
                      </Alert>
                    )}
                  </Box>
                </Collapse>
              </Card>
            );
          })}
        </Box>
      )}
    </Box>
  );
};

export default JobsPage;
