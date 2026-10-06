import React, { Suspense, lazy } from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import Box from '@mui/material/Box';
import CircularProgress from '@mui/material/CircularProgress';
import Typography from '@mui/material/Typography';
import Sidebar from './components/Sidebar';
import ToastContainer from './components/ToastContainer';
import { ToastProvider } from './context/ToastContext';

const SIDEBAR_WIDTH = 230;

const SearchPage       = lazy(() => import('./pages/SearchPage'));
const RepositoriesPage = lazy(() => import('./pages/RepositoriesPage'));
const UploadPage       = lazy(() => import('./pages/UploadPage'));
const JobsPage         = lazy(() => import('./pages/JobsPage'));
const HealthPage       = lazy(() => import('./pages/HealthPage'));

const PageLoader: React.FC = () => (
  <Box
    sx={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      minHeight: '60vh',
      gap: 2,
    }}
  >
    <CircularProgress size={48} />
    <Typography variant="body2" color="text.secondary">
      Loading…
    </Typography>
  </Box>
);

const App: React.FC = () => {
  return (
    <BrowserRouter>
      <ToastProvider>
        <Box sx={{ display: 'flex', minHeight: '100vh', bgcolor: 'background.default' }}>
          <Sidebar width={SIDEBAR_WIDTH} />
          <Box
            component="main"
            sx={{
              flexGrow: 1,
              ml: `${SIDEBAR_WIDTH}px`,
              minHeight: '100vh',
              overflow: 'auto',
            }}
          >
            <Suspense fallback={<PageLoader />}>
              <Routes>
                <Route path="/"             element={<SearchPage />} />
                <Route path="/repositories" element={<RepositoriesPage />} />
                <Route path="/upload"       element={<UploadPage />} />
                <Route path="/jobs"         element={<JobsPage />} />
                <Route path="/health"       element={<HealthPage />} />
                <Route path="*" element={
                  <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '60vh' }}>
                    <Box sx={{ textAlign: 'center' }}>
                      <Typography variant="h3" fontWeight={700} color="text.secondary" gutterBottom>
                        404
                      </Typography>
                      <Typography color="text.secondary">Page not found</Typography>
                    </Box>
                  </Box>
                } />
              </Routes>
            </Suspense>
          </Box>
        </Box>
        <ToastContainer />
      </ToastProvider>
    </BrowserRouter>
  );
};

export default App;
