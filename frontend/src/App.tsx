import React, { Suspense, lazy } from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import Sidebar from './components/Sidebar';
import ToastContainer from './components/ToastContainer';
import { ToastProvider } from './context/ToastContext';

const SearchPage       = lazy(() => import('./pages/SearchPage'));
const RepositoriesPage = lazy(() => import('./pages/RepositoriesPage'));
const UploadPage       = lazy(() => import('./pages/UploadPage'));
const JobsPage         = lazy(() => import('./pages/JobsPage'));
const HealthPage       = lazy(() => import('./pages/HealthPage'));

const PageLoader: React.FC = () => (
  <div className="loading-overlay" style={{ minHeight: '60vh' }}>
    <div className="spinner spinner-lg" />
  </div>
);

const App: React.FC = () => {
  return (
    <BrowserRouter>
      <ToastProvider>
        <div className="app-shell">
          <Sidebar />
          <main className="main-content">
            <Suspense fallback={<PageLoader />}>
              <Routes>
                <Route path="/"              element={<SearchPage />} />
                <Route path="/repositories"  element={<RepositoriesPage />} />
                <Route path="/upload"        element={<UploadPage />} />
                <Route path="/jobs"          element={<JobsPage />} />
                <Route path="/health"        element={<HealthPage />} />
                <Route path="*"             element={
                  <div className="page">
                    <div className="empty-state" style={{ paddingTop: 100 }}>
                      <div className="empty-state-title">404 — Page not found</div>
                    </div>
                  </div>
                } />
              </Routes>
            </Suspense>
          </main>
        </div>
        <ToastContainer />
      </ToastProvider>
    </BrowserRouter>
  );
};

export default App;
