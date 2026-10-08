import React from 'react';
import Snackbar from '@mui/material/Snackbar';
import Alert from '@mui/material/Alert';
import AlertTitle from '@mui/material/AlertTitle';
import Stack from '@mui/material/Stack';
import { useToast } from '../context/ToastContext';
import type { Toast } from '../types';

const severityMap: Record<Toast['type'], 'success' | 'error' | 'warning' | 'info'> = {
  success: 'success',
  error:   'error',
  warning: 'warning',
  info:    'info',
};

const ToastContainer: React.FC = () => {
  const { toasts, removeToast } = useToast();

  return (
    <Stack
      spacing={1}
      sx={{
        position: 'fixed',
        bottom: 24,
        right: 24,
        zIndex: (theme) => theme.zIndex.snackbar,
        maxWidth: 380,
        width: '100%',
      }}
      role="region"
      aria-label="Notifications"
    >
      {toasts.map((t) => (
        <Snackbar
          key={t.id}
          open
          anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
          sx={{ position: 'relative', bottom: 'auto', right: 'auto', transform: 'none' }}
        >
          <Alert
            id={`toast-${t.id}`}
            severity={severityMap[t.type]}
            onClose={() => removeToast(t.id)}
            variant="filled"
            closeText="Dismiss notification"
            sx={{ width: '100%', boxShadow: '0 4px 16px rgba(0,0,0,.5)' }}
            role="alert"
          >
            {t.title && <AlertTitle sx={{ fontWeight: 700 }}>{t.title}</AlertTitle>}
            {t.message}
          </Alert>
        </Snackbar>
      ))}
    </Stack>
  );
};

export default ToastContainer;
