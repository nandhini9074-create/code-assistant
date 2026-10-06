import React, { useState, useEffect, useCallback } from 'react';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Chip from '@mui/material/Chip';
import CircularProgress from '@mui/material/CircularProgress';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableRow from '@mui/material/TableRow';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorIcon from '@mui/icons-material/Error';
import RemoveCircleIcon from "@mui/icons-material/RemoveCircle";
import FiberManualRecordIcon from '@mui/icons-material/FiberManualRecord';
import { healthApi } from '../api/client';
import type { HealthResponse } from '../types';

interface Props {
  compact?: boolean;
}

const statusColors: Record<string, 'success' | 'error' | 'warning' | 'default'> = {
  healthy: 'success',
  ok: 'success',
  degraded: 'warning',
  error: 'error',
  unknown: 'default',
};

const HealthIndicator: React.FC<Props> = ({ compact = false }) => {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const data = await healthApi.check();
      setHealth(data);
    } catch {
      setHealth(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 30_000);
    return () => clearInterval(id);
  }, [refresh]);

  const status = loading ? 'unknown' : health?.status ?? 'degraded';
  const normalizedStatus = status as string;
  const chipColor = statusColors[status] ?? 'default';

  if (compact) {
    return (
      <Box
        id="health-indicator-compact"
        sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}
        title={`API: ${status}`}
      >
        <FiberManualRecordIcon
          sx={{
            fontSize: 10,
            color:
              normalizedStatus === 'ok'
                ? 'success.main'
                : normalizedStatus === 'degraded'
                  ? 'warning.main'
                  : normalizedStatus === 'error'
                    ? 'error.main'
                    : 'text.disabled',
            animation: loading ? 'pulse 2s infinite' : 'none',
            '@keyframes pulse': {
              '0%, 100%': { opacity: 1 },
              '50%': { opacity: 0.4 },
            },
          }}
        />
        <Typography variant="caption" color="text.secondary">
          API {status}
        </Typography>
      </Box>
    );
  }

  const getCheckIcon = (val: string) => {
    if (val === 'ok') return <CheckCircleIcon fontSize="small" color="success" />;
    if (val === 'disabled') return <RemoveCircleIcon fontSize="small" color="disabled" />;
    return <ErrorIcon fontSize="small" color="error" />;
  };

  return (
    <Box id="health-indicator-full">
      {loading ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 2 }}>
          <CircularProgress size={24} />
        </Box>
      ) : !health ? (
        <Typography variant="body2" color="error.main">
          Cannot reach backend
        </Typography>
      ) : (
        <>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 2 }}>
            <Typography variant="body2" color="text.secondary">
              Overall Status
            </Typography>
            <Chip
              label={status.toUpperCase()}
              color={chipColor}
              size="small"
              variant="outlined"
              sx={{ fontWeight: 700, fontSize: 11 }}
            />
          </Box>

          <Table size="small">
            <TableBody>
              {Object.entries(health.checks).map(([key, val]) => (
                <TableRow key={key}>
                  <TableCell sx={{ pl: 0, borderBottom: 'none', py: 0.75 }}>
                    <Typography variant="body2" color="text.secondary">
                      {key}
                    </Typography>
                  </TableCell>
                  <TableCell align="right" sx={{ pr: 0, borderBottom: 'none', py: 0.75 }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 0.5 }}>
                      {getCheckIcon(val)}
                      <Typography
                        variant="body2"
                        sx={{ fontWeight: 600 }}
                        color={
                          val === 'ok'
                            ? 'success.main'
                            : val === 'disabled'
                              ? 'text.disabled'
                              : 'error.main'
                        }
                      >
                        {val}
                      </Typography>
                    </Box>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </>
      )}
    </Box>
  );
};

export default HealthIndicator;
