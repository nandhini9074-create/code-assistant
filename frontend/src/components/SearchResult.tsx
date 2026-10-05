import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { SearchResponse } from '../types';
import CodeBlock from './CodeBlock';
import {
  Lightbulb,
  Target,
  FileCode,
  AlertCircle,
  GitCompare,
  Sparkles,
  Users,
  CheckCircle,
} from 'lucide-react';

interface Props {
  response: SearchResponse;
  query: string;
}

const intentLabel: Record<string, string> = {
  EXPLAIN:        'Explain',
  FIX_BUG:       'Fix Bug',
  OPTIMIZE:       'Optimize',
  REFACTOR:       'Refactor',
  FIND_USAGE:     'Find Usage',
  FIND_FUNCTION:  'Find Function',
  FIND_CLASS:     'Find Class',
  ARCHITECTURE:   'Architecture',
  SECURITY:       'Security',
  GENERAL:        'General',
};

const SearchResult: React.FC<Props> = ({ response, query }) => {
  const label = intentLabel[response.intent] ?? response.intent;

  /* Detect language from target or file path */
  const detectLang = (filePath?: string) => {
    if (!filePath) return 'python';
    if (filePath.endsWith('.ts') || filePath.endsWith('.tsx')) return 'typescript';
    if (filePath.endsWith('.js') || filePath.endsWith('.jsx')) return 'javascript';
    if (filePath.endsWith('.go')) return 'go';
    if (filePath.endsWith('.rs')) return 'rust';
    if (filePath.endsWith('.java')) return 'java';
    if (filePath.endsWith('.rb')) return 'ruby';
    if (filePath.endsWith('.sh')) return 'bash';
    return 'python';
  };

  const targetFile = response.target?.file_path as string | undefined;
  const lang = detectLang(targetFile);

  /* Early exit */
  if (response.early_exit) {
    return (
      <div className="result-card animate-fade">
        <div className="result-header">
          <div>
            <div style={{ fontSize: 13, color: 'var(--color-text-muted)', marginBottom: 4 }}>Query</div>
            <div style={{ fontSize: 15, fontWeight: 600 }}>{query}</div>
          </div>
          <span className="result-intent-badge"><AlertCircle size={12} />{label}</span>
        </div>
        <div className="result-body">
          <div className="result-section">
            <div className="result-section-label"><AlertCircle size={11} />Notice</div>
            <div className="result-text prose">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {String(response.early_exit.message ?? 'No further information available.')}
              </ReactMarkdown>
            </div>
          </div>
        </div>
      </div>
    );
  }

  /* Ambiguous candidates */
  if (response.ambiguous_candidates.length > 0) {
    return (
      <div className="result-card animate-fade">
        <div className="result-header">
          <div>
            <div style={{ fontSize: 13, color: 'var(--color-text-muted)', marginBottom: 4 }}>Query</div>
            <div style={{ fontSize: 15, fontWeight: 600 }}>{query}</div>
          </div>
          <span className="result-intent-badge"><Users size={12} />Ambiguous</span>
        </div>
        <div className="result-body">
          <div className="result-section">
            <div className="result-section-label"><Users size={11} />Multiple Matches Found</div>
            <p className="result-text" style={{ marginBottom: 12 }}>
              The symbol <strong>{response.ambiguous_candidates[0].name}</strong> exists in multiple files.
              Please refine your query with more context:
            </p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {response.ambiguous_candidates.map((c, i) => (
                <div
                  key={i}
                  className="card card-sm"
                  style={{ background: 'var(--color-bg-elevated)', borderRadius: 'var(--radius-md)' }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span className="result-target-file"><FileCode size={12} />{c.file_path}</span>
                    {c.score != null && (
                      <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
                        score: {c.score.toFixed(3)}
                      </span>
                    )}
                  </div>
                  {c.class_name && (
                    <div style={{ fontSize: 12, color: 'var(--color-text-muted)', marginTop: 4 }}>
                      Class: {c.class_name}
                    </div>
                  )}
                  {c.start_line != null && (
                    <div style={{ fontSize: 12, color: 'var(--color-text-muted)', marginTop: 2 }}>
                      Lines {c.start_line}–{c.end_line}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="result-card animate-fade">
      {/* Header */}
      <div className="result-header">
        <div>
          <div style={{ fontSize: 13, color: 'var(--color-text-muted)', marginBottom: 4 }}>Query</div>
          <div style={{ fontSize: 15, fontWeight: 600 }}>{query}</div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 8 }}>
          <span className="result-intent-badge"><Sparkles size={12} />{label}</span>
          {response.confidence && (
            <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
              Confidence: {response.confidence}
            </span>
          )}
        </div>
      </div>

      <div className="result-body">
        {/* Target */}
        {response.target && (
          <div className="result-section">
            <div className="result-section-label"><Target size={11} />Target</div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {targetFile && (
                <span className="result-target-file"><FileCode size={12} />{targetFile}</span>
              )}
              {response.target.name && (
                <span className="result-target-file" style={{ color: 'var(--color-text-accent)' }}>
                  {String(response.target.name)}
                </span>
              )}
              {response.target.start_line != null && (
                <span style={{ fontSize: 12, color: 'var(--color-text-muted)', alignSelf: 'center' }}>
                  L{String(response.target.start_line)}–{String(response.target.end_line)}
                </span>
              )}
            </div>
          </div>
        )}

        {/* Formatted output (main LLM answer) */}
        {response.formatted_output && (
          <div className="result-section">
            <div className="result-section-label"><Lightbulb size={11} />Analysis</div>
            <div className="result-text prose">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{response.formatted_output}</ReactMarkdown>
            </div>
          </div>
        )}

        {/* Suggestion */}
        {response.suggestion && !response.formatted_output && (
          <div className="result-section">
            <div className="result-section-label"><Lightbulb size={11} />Suggestion</div>
            <div className="result-text prose">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{response.suggestion}</ReactMarkdown>
            </div>
          </div>
        )}

        {/* Current behavior */}
        {response.current_behavior && (
          <div className="result-section">
            <div className="result-section-label"><AlertCircle size={11} />Current Behavior</div>
            <div className="result-text prose">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{response.current_behavior}</ReactMarkdown>
            </div>
          </div>
        )}

        {/* Proposed change */}
        {response.proposed_change && (
          <div className="result-section">
            <div className="result-section-label"><GitCompare size={11} />Proposed Change</div>
            <div className="result-text prose">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{response.proposed_change}</ReactMarkdown>
            </div>
          </div>
        )}

        {/* Suggested code */}
        {response.suggested_code && (
          <div className="result-section">
            <div className="result-section-label"><FileCode size={11} />Suggested Code</div>
            <CodeBlock
              code={response.suggested_code}
              language={lang}
              filename={targetFile}
            />
          </div>
        )}

        {/* Suggested patch */}
        {response.suggested_patch && !response.suggested_code && (
          <div className="result-section">
            <div className="result-section-label"><GitCompare size={11} />Suggested Patch</div>
            <CodeBlock
              code={response.suggested_patch}
              language="diff"
              filename="patch.diff"
            />
          </div>
        )}

        {/* Patch validation */}
        {response.patch_validation && (
          <div className="result-section">
            <div className="result-section-label">
              <CheckCircle size={11} />Patch Validation
            </div>
            <div className="kv-list">
              {Object.entries(response.patch_validation).map(([k, v]) => (
                <div className="kv-row" key={k}>
                  <span className="kv-key">{k}</span>
                  <span className="kv-value">{String(v)}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default SearchResult;
