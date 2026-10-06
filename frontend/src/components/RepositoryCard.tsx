import React from 'react';
import type { Repository } from '../types';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import CardActions from '@mui/material/CardActions';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Chip from '@mui/material/Chip';
import Button from '@mui/material/Button';
import IconButton from '@mui/material/IconButton';
import Divider from '@mui/material/Divider';
import Tooltip from '@mui/material/Tooltip';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableRow from '@mui/material/TableRow';
import AccountTreeIcon from '@mui/icons-material/AccountTree';
import DeleteIcon from '@mui/icons-material/Delete';
import RefreshIcon from '@mui/icons-material/Refresh';
import OpenInNewIcon from '@mui/icons-material/OpenInNew';
import WorkHistoryIcon from '@mui/icons-material/WorkHistory';
import CircleIcon from '@mui/icons-material/Circle';

interface Props {
  repo: Repository;
  onDelete: (id: string) => void;
  onReindex: (id: string) => void;
  onViewJobs: (id: string) => void;
}

const statusConfig: Record<string, { label: string; color: 'success' | 'warning' | 'error' | 'info' | 'default' }> = {
  indexed:  { label: 'Indexed',  color: 'success' },
  pending:  { label: 'Pending',  color: 'warning' },
  indexing: { label: 'Indexing', color: 'info' },
  error:    { label: 'Error',    color: 'error' },
  stale:    { label: 'Stale',    color: 'warning' },
};

const RepositoryCard: React.FC<Props> = ({ repo, onDelete, onReindex, onViewJobs }) => {
  const sc = statusConfig[repo.status] ?? { label: repo.status, color: 'default' };

  return (
    <Card
      role="article"
      aria-label={`Repository: ${repo.full_name}`}
      id={`repo-card-${repo.id}`}
      sx={{
        display: 'flex',
        flexDirection: 'column',
        transition: 'transform 0.2s ease, box-shadow 0.2s ease',
        '&:hover': {
          transform: 'translateY(-2px)',
          boxShadow: '0 8px 32px rgba(0,0,0,.6)',
        },
      }}
    >
      <CardContent sx={{ flex: 1, pb: 1 }}>
        {/* Header */}
        <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1, mb: 1 }}>
          <AccountTreeIcon sx={{ color: 'primary.main', mt: 0.3, flexShrink: 0 }} />
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Typography variant="subtitle1" fontWeight={700} noWrap>
              {repo.name}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {repo.owner}
            </Typography>
          </Box>
          <Chip
            label={sc.label}
            color={sc.color}
            size="small"
            variant="outlined"
            sx={{ fontWeight: 700, fontSize: 11, flexShrink: 0 }}
          />
        </Box>

        <Divider sx={{ my: 1.5 }} />

        {/* Metadata table */}
        <Table size="small" sx={{ '& td': { px: 0, py: 0.5, border: 'none' } }}>
          <TableBody>
            <TableRow>
              <TableCell>
                <Typography variant="caption" color="text.secondary">Collection</Typography>
              </TableCell>
              <TableCell align="right">
                <Typography
                  variant="caption"
                  fontFamily="'JetBrains Mono', monospace"
                  sx={{ maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', display: 'block', textAlign: 'right' }}
                >
                  {repo.qdrant_collection}
                </Typography>
              </TableCell>
            </TableRow>
            {repo.current_commit_sha && (
              <TableRow>
                <TableCell>
                  <Typography variant="caption" color="text.secondary">Commit</Typography>
                </TableCell>
                <TableCell align="right">
                  <Typography variant="caption" fontFamily="'JetBrains Mono', monospace">
                    {repo.current_commit_sha.slice(0, 12)}
                  </Typography>
                </TableCell>
              </TableRow>
            )}
            <TableRow>
              <TableCell>
                <Typography variant="caption" color="text.secondary">Webhook</Typography>
              </TableCell>
              <TableCell align="right">
                <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 0.5 }}>
                  <CircleIcon
                    sx={{
                      fontSize: 8,
                      color: repo.webhook_configured ? 'success.main' : 'text.disabled',
                    }}
                  />
                  <Typography variant="caption" color={repo.webhook_configured ? 'success.main' : 'text.disabled'}>
                    {repo.webhook_configured ? 'Active' : 'Not set'}
                  </Typography>
                </Box>
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </CardContent>

      <Divider />

      <CardActions sx={{ px: 1.5, py: 1, gap: 0.5 }}>
        <Button
          id={`repo-github-${repo.id}`}
          component="a"
          href={repo.github_url}
          target="_blank"
          rel="noopener noreferrer"
          size="small"
          startIcon={<OpenInNewIcon />}
          aria-label={`Open ${repo.full_name} on GitHub`}
          sx={{ color: 'text.secondary', '&:hover': { color: 'primary.main' } }}
        >
          GitHub
        </Button>

        <Button
          id={`repo-jobs-${repo.id}`}
          size="small"
          startIcon={<WorkHistoryIcon />}
          onClick={() => onViewJobs(repo.id)}
          aria-label={`View jobs for ${repo.name}`}
          sx={{ color: 'text.secondary', '&:hover': { color: 'secondary.main' } }}
        >
          Jobs
        </Button>

        <Button
          id={`repo-reindex-${repo.id}`}
          size="small"
          startIcon={<RefreshIcon />}
          onClick={() => onReindex(repo.id)}
          aria-label={`Reindex ${repo.name}`}
          sx={{ color: 'text.secondary', '&:hover': { color: 'info.main' } }}
        >
          Reindex
        </Button>

        <Box sx={{ flex: 1 }} />

        <Tooltip title="Delete repository">
          <IconButton
            id={`repo-delete-${repo.id}`}
            size="small"
            color="error"
            onClick={() => onDelete(repo.id)}
            aria-label={`Delete ${repo.name}`}
          >
            <DeleteIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </CardActions>
    </Card>
  );
};

export default RepositoryCard;
