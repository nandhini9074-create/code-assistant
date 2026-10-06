import React, { useState, useCallback, useRef, useEffect } from 'react';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Button from '@mui/material/Button';
import ButtonGroup from '@mui/material/ButtonGroup';
import TextField from '@mui/material/TextField';
import InputAdornment from '@mui/material/InputAdornment';
import Chip from '@mui/material/Chip';
import CircularProgress from '@mui/material/CircularProgress';
import Paper from '@mui/material/Paper';
import Card from '@mui/material/Card';
import CardActionArea from '@mui/material/CardActionArea';
import CardContent from '@mui/material/CardContent';
import Divider from '@mui/material/Divider';
import SearchIcon from '@mui/icons-material/Search';
import AccountTreeIcon from '@mui/icons-material/AccountTree';
import FolderZipIcon from '@mui/icons-material/FolderZip';
import ShieldIcon from '@mui/icons-material/Shield';
import { searchApi } from '../api/client';
import type { SearchRequest, SearchResponse, SourceType, SearchHistoryItem } from '../types';
import { useToast } from '../context/ToastContext';
import SearchResult from '../components/SearchResult';
import PipelineLoader, { PIPELINE_STAGES } from '../components/PipelineLoader';

const EXAMPLE_QUERIES = [
  'Explain how authentication works',
  'Find the main entry point function',
  'Fix the bug in the pagination logic',
  'How is the database connection managed?',
  'Where is error handling implemented?',
];

const SearchPage: React.FC = () => {
  const { addToast } = useToast();

  const [query, setQuery] = useState('');
  const [sourceType, setSourceType] = useState<SourceType>('git');
  const [location, setLocation] = useState('');
  const [loading, setLoading] = useState(false);
  const [history, setHistory] = useState<SearchHistoryItem[]>([]);
  const [activeResult, setActiveResult] = useState<SearchHistoryItem | null>(null);

  const [currentStageIndex, setCurrentStageIndex] = useState(0);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const stageTimeoutRef = useRef<number | null>(null);
  const elapsedIntervalRef = useRef<number | null>(null);

  const clearTimers = useCallback(() => {
    if (stageTimeoutRef.current !== null) {
      window.clearTimeout(stageTimeoutRef.current);
      stageTimeoutRef.current = null;
    }
    if (elapsedIntervalRef.current !== null) {
      window.clearInterval(elapsedIntervalRef.current);
      elapsedIntervalRef.current = null;
    }
  }, []);

  useEffect(() => { return () => clearTimers(); }, [clearTimers]);

  const handleSearch = useCallback(async (searchQuery = query) => {
    if (!searchQuery.trim()) return addToast('warning', 'Query required', 'Please enter a search query.');
    if (!location.trim()) return addToast('warning', 'Source required', 'Please enter a repository URL or ZIP location.');

    const request: SearchRequest = {
      source: { type: sourceType, location: location.trim() },
      query: searchQuery.trim(),
    };

    clearTimers();
    setCurrentStageIndex(0);
    setElapsedSeconds(0);
    setLoading(true);

    const startTime = Date.now();
    elapsedIntervalRef.current = window.setInterval(() => {
      setElapsedSeconds((Date.now() - startTime) / 1000);
    }, 100);

    const scheduleNextStage = (stageIdx: number) => {
      if (stageIdx >= PIPELINE_STAGES.length - 1) return;
      const stage = PIPELINE_STAGES[stageIdx];
      stageTimeoutRef.current = window.setTimeout(() => {
        const nextIdx = stageIdx + 1;
        setCurrentStageIndex(nextIdx);
        scheduleNextStage(nextIdx);
      }, stage.typicalDurationMs);
    };

    scheduleNextStage(0);

    try {
      const response: SearchResponse = await searchApi.search(request);
      const item: SearchHistoryItem = {
        id: crypto.randomUUID(),
        query: request.query,
        source: request.source,
        timestamp: Date.now(),
        response,
      };
      setHistory((prev) => [item, ...prev]);
      setActiveResult(item);
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Search failed';
      addToast('error', 'Search failed', msg);
    } finally {
      clearTimers();
      setLoading(false);
    }
  }, [query, sourceType, location, addToast, clearTimers]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSearch();
    }
  };

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', minHeight: '100%' }}>
      {/* Hero search bar */}
      <Paper
        elevation={0}
        sx={{
          px: { xs: 2, md: 4 },
          py: 3,
          bgcolor: 'hsl(222, 18%, 9%)',
          borderBottom: '1px solid',
          borderColor: 'divider',
          position: 'sticky',
          top: 0,
          zIndex: 10,
        }}
      >
        <Typography variant="h4" fontWeight={800} gutterBottom>
          Search Your Codebase
        </Typography>
        <Typography variant="body2" color="text.secondary" mb={2.5}>
          Ask questions in natural language — CodeLens retrieves, analyzes, and explains relevant code.
        </Typography>

        {/* Source type toggle */}
        <ButtonGroup size="small" variant="outlined" aria-label="Source type" sx={{ mb: 2 }}>
          <Button
            id="source-pill-git"
            startIcon={<AccountTreeIcon />}
            onClick={() => setSourceType('git')}
            variant={sourceType === 'git' ? 'contained' : 'outlined'}
            sx={{ fontWeight: 600 }}
          >
            GitHub URL
          </Button>
          <Button
            id="source-pill-zip"
            startIcon={<FolderZipIcon />}
            onClick={() => setSourceType('zip')}
            variant={sourceType === 'zip' ? 'contained' : 'outlined'}
            sx={{ fontWeight: 600 }}
          >
            ZIP Path
          </Button>
        </ButtonGroup>

        {/* Location input */}
        <TextField
          id="search-location"
          fullWidth
          placeholder={
            sourceType === 'git'
              ? 'https://github.com/owner/repo'
              : 'local://repo-name.zip'
          }
          value={location}
          onChange={(e) => setLocation(e.target.value)}
          aria-label="Repository location"
          size="small"
          sx={{ mb: 1.5 }}
        />

        {/* Query + search buttons */}
        <Box sx={{ display: 'flex', gap: 1 }}>
          <TextField
            id="search-query"
            fullWidth
            placeholder="Ask anything about your code…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            aria-label="Search query"
            disabled={loading}
            size="small"
            InputProps={{
              startAdornment: (
                <InputAdornment position="start">
                  <SearchIcon fontSize="small" sx={{ color: 'text.secondary' }} />
                </InputAdornment>
              ),
            }}
          />
          <Button
            id="search-submit"
            variant="contained"
            onClick={() => handleSearch()}
            disabled={loading}
            aria-label="Run search"
            startIcon={loading ? <CircularProgress size={16} color="inherit" /> : <SearchIcon />}
            sx={{ whiteSpace: 'nowrap', minWidth: 120 }}
          >
            {loading ? 'Searching…' : 'Search'}
          </Button>
          <Button
            id="npm-audit-submit"
            variant="outlined"
            onClick={() => handleSearch('Run npm audit')}
            disabled={loading}
            title="Audit project dependencies"
            startIcon={<ShieldIcon />}
            sx={{ whiteSpace: 'nowrap' }}
          >
            NPM Audit
          </Button>
        </Box>

        {/* Example queries */}
        {!activeResult && (
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.75, mt: 1.5 }}>
            {EXAMPLE_QUERIES.map((q) => (
              <Chip
                key={q}
                label={q}
                size="small"
                variant="outlined"
                clickable
                onClick={() => setQuery(q)}
                sx={{ fontSize: 11, '&:hover': { borderColor: 'primary.main', color: 'primary.light' } }}
              />
            ))}
          </Box>
        )}
      </Paper>

      {/* Results area */}
      <Box sx={{ px: { xs: 2, md: 4 }, py: 3, flex: 1 }}>
        {loading && (
          <PipelineLoader
            currentStageIndex={currentStageIndex}
            elapsedSeconds={elapsedSeconds}
          />
        )}

        {!loading && activeResult?.response && (
          <SearchResult response={activeResult.response} query={activeResult.query} />
        )}

        {/* History */}
        {!loading && history.length > 1 && (
          <Box sx={{ mt: 3.5 }}>
            <Typography variant="caption" fontWeight={700} color="text.secondary" textTransform="uppercase" letterSpacing="0.08em" display="block" mb={1.5}>
              Previous Searches
            </Typography>
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
              {history.slice(1).map((item) => (
                <Card
                  key={item.id}
                  id={`history-${item.id}`}
                  variant="outlined"
                  sx={{
                    cursor: 'pointer',
                    borderColor: activeResult?.id === item.id ? 'primary.main' : 'divider',
                    bgcolor: activeResult?.id === item.id ? 'hsla(258,90%,66%,0.07)' : 'transparent',
                  }}
                >
                  <CardActionArea onClick={() => setActiveResult(item)}>
                    <CardContent sx={{ py: 1.25, '&:last-child': { pb: 1.25 } }}>
                      <Typography variant="body2" fontWeight={600} noWrap>{item.query}</Typography>
                      <Typography variant="caption" color="text.secondary">
                        {item.source.location} · {new Date(item.timestamp).toLocaleTimeString()}
                      </Typography>
                    </CardContent>
                  </CardActionArea>
                </Card>
              ))}
            </Box>
          </Box>
        )}

        {/* Empty state */}
        {!loading && history.length === 0 && (
          <Box
            sx={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              minHeight: '40vh',
              gap: 2,
              textAlign: 'center',
            }}
          >
            <Box
              sx={{
                width: 80,
                height: 80,
                borderRadius: '50%',
                bgcolor: 'hsla(258,90%,66%,0.1)',
                border: '1px solid hsla(258,90%,66%,0.2)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <SearchIcon sx={{ fontSize: 36, color: 'primary.main' }} />
            </Box>
            <Box>
              <Typography variant="h6" fontWeight={700} gutterBottom>
                Ready to explore
              </Typography>
              <Typography variant="body2" color="text.secondary" maxWidth={440}>
                Enter a repository URL and a natural-language question to get started.
                CodeLens will retrieve relevant code and provide AI-powered analysis.
              </Typography>
            </Box>
          </Box>
        )}
      </Box>
    </Box>
  );
};

export default SearchPage;
