import React, { useState, useCallback, useRef, useEffect } from 'react';
import { Search, GitBranch, Archive, Loader2, ShieldCheck } from 'lucide-react';
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

  // Pipeline stage progression state
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

  useEffect(() => {
    return () => clearTimers();
  }, [clearTimers]);

  const handleSearch = useCallback(async (searchQuery = query) => {
    if (!searchQuery.trim()) return addToast('warning', 'Query required', 'Please enter a search query.');
    if (!location.trim()) return addToast('warning', 'Source required', 'Please enter a repository URL or ZIP location.');

    const request: SearchRequest = {
      source: { type: sourceType, location: location.trim() },
      query: searchQuery.trim(),
    };

    // Reset & start pipeline tracking
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
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100%' }}>
      {/* Hero search bar */}
      <div className="search-bar-wrap">
        <h1 className="search-hero-title">Search Your Codebase</h1>
        <p className="search-hero-sub">
          Ask questions in natural language — CodeLens retrieves, analyzes, and explains relevant code.
        </p>

        {/* Source type pills */}
        <div className="source-pills" role="group" aria-label="Source type">
          <button
            id="source-pill-git"
            className={`source-pill ${sourceType === 'git' ? 'active' : ''}`}
            onClick={() => setSourceType('git')}
          >
            <GitBranch size={13} /> GitHub URL
          </button>
          <button
            id="source-pill-zip"
            className={`source-pill ${sourceType === 'zip' ? 'active' : ''}`}
            onClick={() => setSourceType('zip')}
          >
            <Archive size={13} /> ZIP Path
          </button>
        </div>

        {/* Location input */}
        <div className="form-group" style={{ marginBottom: 10 }}>
          <input
            id="search-location"
            className="form-input"
            placeholder={
              sourceType === 'git'
                ? 'https://github.com/owner/repo'
                : 'local://repo-name.zip'
            }
            value={location}
            onChange={(e) => setLocation(e.target.value)}
            aria-label="Repository location"
          />
        </div>

        {/* Query input + send button */}
        <div className="search-input-row">
          <div className="search-input-group">
            <Search size={17} className="search-input-icon" />
            <input
              id="search-query"
              className="search-input"
              placeholder="Ask anything about your code…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              aria-label="Search query"
              disabled={loading}
            />
          </div>
          <button
            id="search-submit"
            className="btn btn-primary btn-lg"
            onClick={() => handleSearch()}
            disabled={loading}
            aria-label="Run search"
          >
            {loading ? <Loader2 size={16} className="animate-pulse" /> : <Search size={16} />}
            {loading ? 'Searching…' : 'Search'}
          </button>
          <button
            id="npm-audit-submit"
            className="btn btn-secondary btn-lg"
            onClick={() => handleSearch('Run npm audit')}
            disabled={loading}
            title="Audit project dependencies"
          >
            <ShieldCheck size={16} />
            NPM Audit
          </button>
        </div>

        {/* Example queries */}
        {!activeResult && (
          <div style={{ marginTop: 14, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {EXAMPLE_QUERIES.map((q) => (
              <button
                key={q}
                className="btn btn-ghost btn-sm"
                style={{
                  fontSize: 12,
                  border: '1px solid var(--color-border)',
                  borderRadius: 999,
                }}
                onClick={() => setQuery(q)}
              >
                {q}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Results area */}
      <div className="page" style={{ maxWidth: '100%' }}>
        {loading && (
          <PipelineLoader
            currentStageIndex={currentStageIndex}
            elapsedSeconds={elapsedSeconds}
          />
        )}

        {!loading && activeResult?.response && (
          <SearchResult response={activeResult.response} query={activeResult.query} />
        )}

        {/* History sidebar */}
        {!loading && history.length > 1 && (
          <div style={{ marginTop: 28 }}>
            <h2 style={{ fontSize: 14, fontWeight: 600, color: 'var(--color-text-muted)', marginBottom: 12 }}>
              Previous Searches
            </h2>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {history.slice(1).map((item) => (
                <button
                  key={item.id}
                  id={`history-${item.id}`}
                  className="card card-sm"
                  style={{
                    cursor: 'pointer',
                    textAlign: 'left',
                    background: activeResult?.id === item.id ? 'var(--color-bg-elevated)' : undefined,
                    border: activeResult?.id === item.id ? '1px solid var(--color-accent)' : undefined,
                  }}
                  onClick={() => setActiveResult(item)}
                >
                  <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 2 }}>{item.query}</div>
                  <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
                    {item.source.location} · {new Date(item.timestamp).toLocaleTimeString()}
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Empty state */}
        {!loading && history.length === 0 && (
          <div className="empty-state" style={{ paddingTop: 80 }}>
            <div className="empty-state-icon"><Search size={48} /></div>
            <div className="empty-state-title">Ready to explore</div>
            <div className="empty-state-sub">
              Enter a repository URL and a natural-language question to get started.
              CodeLens will retrieve relevant code and provide AI-powered analysis.
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default SearchPage;
