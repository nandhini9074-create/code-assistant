import React, { useState } from 'react';
import {
  ShieldCheck,
  Compass,
  Filter,
  Database,
  Search,
  FileCode,
  Layers,
  Cpu,
  Zap,
  Wrench,
  CheckCircle2,
  Sparkles,
  Check,
  Loader2,
  Clock,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';

export interface PipelineStageInfo {
  number: number;
  name: string;
  shortName: string;
  loadingMessage: string;
  detail: string;
  typicalDurationMs: number;
}

export const PIPELINE_STAGES: PipelineStageInfo[] = [
  {
    number: 1,
    name: 'Request Validation',
    shortName: 'Validation',
    loadingMessage: 'Validating request query parameters and repository source...',
    detail: 'Verifies query format, repository target existence, and user constraints.',
    typicalDurationMs: 700,
  },
  {
    number: 2,
    name: 'Intent Classification',
    shortName: 'Intent',
    loadingMessage: 'Classifying query intent and search strategy...',
    detail: 'Determines whether query is explain, debug, fix, search, or architectural inquiry.',
    typicalDurationMs: 900,
  },
  {
    number: 3,
    name: 'Query Preprocessing',
    shortName: 'Preprocessing',
    loadingMessage: 'Extracting keywords, function identifiers, and syntax tokens...',
    detail: 'Normalizes search terms and separates natural language from code identifiers.',
    typicalDurationMs: 800,
  },
  {
    number: 4,
    name: 'Collection Selection',
    shortName: 'Collection',
    loadingMessage: 'Selecting repository vector collection in Qdrant...',
    detail: 'Resolves repository name to active Qdrant vector database namespace.',
    typicalDurationMs: 700,
  },
  {
    number: 5,
    name: 'Code Retrieval',
    shortName: 'Retrieval',
    loadingMessage: 'Searching vector database for matching code chunks and embeddings...',
    detail: 'Performs semantic vector search against indexed AST chunks and code snippets.',
    typicalDurationMs: 1600,
  },
  {
    number: 6,
    name: 'Code Identification',
    shortName: 'Identification',
    loadingMessage: 'Identifying primary classes, functions, and target symbols...',
    detail: 'Pins exact symbol definitions and resolves any ambiguous identifier candidates.',
    typicalDurationMs: 1200,
  },
  {
    number: 7,
    name: 'Context Builder',
    shortName: 'Context',
    loadingMessage: 'Assembling complete context window with cross-file references...',
    detail: 'Builds coherent prompt context with imports, callers, and related implementations.',
    typicalDurationMs: 1000,
  },
  {
    number: 8,
    name: 'Code Analysis',
    shortName: 'Analysis',
    loadingMessage: 'Running deep semantic code analysis with AI model...',
    detail: 'LLM evaluates code logic, dependencies, control flows, and potential issues.',
    typicalDurationMs: 3500,
  },
  {
    number: 9,
    name: 'Evidence Validation',
    shortName: 'Evidence',
    loadingMessage: 'Validating analysis evidence against actual codebase facts...',
    detail: 'Ensures reasoning is strictly grounded in retrieved chunks without hallucination.',
    typicalDurationMs: 1200,
  },
  {
    number: 10,
    name: 'Action Analysis',
    shortName: 'Action Planning',
    loadingMessage: 'Planning remediation actions, refactoring, and code changes...',
    detail: 'Formulates concrete action plan and architectural recommendations.',
    typicalDurationMs: 1500,
  },
  {
    number: 11,
    name: 'Suggestion Patch',
    shortName: 'Patch Gen',
    loadingMessage: 'Generating suggested code modifications and unified diffs...',
    detail: 'Produces precise line-by-line diffs and code patch replacements.',
    typicalDurationMs: 2200,
  },
  {
    number: 12,
    name: 'Suggestion Validation',
    shortName: 'Patch Validation',
    loadingMessage: 'Validating suggested patch syntax, integrity, and safety...',
    detail: 'Checks patch consistency against original source code structure.',
    typicalDurationMs: 1000,
  },
  {
    number: 13,
    name: 'Final Triage',
    shortName: 'Final Triage',
    loadingMessage: 'Performing safety checks, confidence scoring, and candidate ranking...',
    detail: 'Ranks final recommendations and verifies security guardrails.',
    typicalDurationMs: 900,
  },
  {
    number: 14,
    name: 'Response Generation',
    shortName: 'Response Gen',
    loadingMessage: 'Synthesizing final structured response and formatted explanation...',
    detail: 'Formats answer with markdown, code highlights, and actionable suggestions.',
    typicalDurationMs: 1800,
  },
];

interface PipelineLoaderProps {
  currentStageIndex: number;
  elapsedSeconds: number;
}

const getStageIcon = (stageNumber: number, size = 16) => {
  switch (stageNumber) {
    case 1:
      return <ShieldCheck size={size} />;
    case 2:
      return <Compass size={size} />;
    case 3:
      return <Filter size={size} />;
    case 4:
      return <Database size={size} />;
    case 5:
      return <Search size={size} />;
    case 6:
      return <FileCode size={size} />;
    case 7:
      return <Layers size={size} />;
    case 8:
      return <Cpu size={size} />;
    case 9:
      return <ShieldCheck size={size} />;
    case 10:
      return <Zap size={size} />;
    case 11:
      return <Wrench size={size} />;
    case 12:
      return <CheckCircle2 size={size} />;
    case 13:
      return <Sparkles size={size} />;
    case 14:
      return <Check size={size} />;
    default:
      return <Loader2 size={size} />;
  }
};

export const PipelineLoader: React.FC<PipelineLoaderProps> = ({
  currentStageIndex,
  elapsedSeconds,
}) => {
  const [showAllStages, setShowAllStages] = useState(true);

  const totalStages = PIPELINE_STAGES.length;
  const clampedIndex = Math.min(Math.max(currentStageIndex, 0), totalStages - 1);
  const activeStage = PIPELINE_STAGES[clampedIndex];
  const progressPercent = Math.min(
    Math.round(((clampedIndex + 0.6) / totalStages) * 100),
    98
  );

  return (
    <div className="pipeline-loader-card" role="region" aria-label="Search pipeline progress">
      {/* Glow highlight backdrop */}
      <div className="pipeline-loader-glow" />

      {/* Header bar */}
      <div className="pipeline-loader-header">
        <div className="pipeline-loader-title-group">
          <div className="pipeline-pulse-badge">
            <span className="pipeline-pulse-dot" />
            <span className="pipeline-badge-text">PIPELINE RUNNING</span>
          </div>
          <h2 className="pipeline-title">Executing Deep Search Pipeline</h2>
          <p className="pipeline-subtitle">
            Analyzing repository semantics, extracting references, and generating insights
          </p>
        </div>

        <div className="pipeline-metrics">
          <div className="pipeline-metric-badge">
            <Clock size={14} className="pipeline-timer-icon" />
            <span>{elapsedSeconds.toFixed(1)}s elapsed</span>
          </div>
          <div className="pipeline-metric-badge stage-counter-badge">
            Stage {activeStage.number} of {totalStages}
          </div>
        </div>
      </div>

      {/* Progress Bar */}
      <div className="pipeline-progress-container">
        <div className="pipeline-progress-track">
          <div
            className="pipeline-progress-fill"
            style={{ width: `${progressPercent}%` }}
          />
        </div>
        <div className="pipeline-progress-labels">
          <span className="pipeline-progress-hint">
            Step {activeStage.number} &mdash; {activeStage.name}
          </span>
          <span className="pipeline-progress-value">{progressPercent}%</span>
        </div>
      </div>

      {/* Hero Active Stage Banner */}
      <div className="pipeline-active-stage-card">
        <div className="pipeline-active-stage-header">
          <div className="pipeline-stage-icon-wrap">
            <div className="pipeline-stage-spinner" />
            <span className="pipeline-stage-icon">
              {getStageIcon(activeStage.number, 20)}
            </span>
          </div>
          <div className="pipeline-active-info">
            <div className="pipeline-stage-meta">
              <span className="pipeline-stage-pill">
                STAGE {String(activeStage.number).padStart(2, '0')}
              </span>
              <span className="pipeline-stage-name">{activeStage.name}</span>
            </div>
            <div className="pipeline-stage-msg">
              <Loader2 size={15} className="pipeline-spin-icon" />
              <span>{activeStage.loadingMessage}</span>
            </div>
          </div>
        </div>

        <p className="pipeline-stage-desc">{activeStage.detail}</p>
      </div>

      {/* Toggle View for Pipeline Stages List */}
      <div className="pipeline-stages-accordion-toggle">
        <button
          type="button"
          className="btn btn-ghost btn-sm pipeline-accordion-btn"
          onClick={() => setShowAllStages((prev) => !prev)}
          aria-expanded={showAllStages}
        >
          <span>
            {showAllStages ? 'Hide full stage breakdown' : 'Show all 14 pipeline stages'}
          </span>
          {showAllStages ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </button>
      </div>

      {/* All Stages Stepper Grid / List */}
      {showAllStages && (
        <div className="pipeline-stepper-grid">
          {PIPELINE_STAGES.map((stage, idx) => {
            const isCompleted = idx < clampedIndex;
            const isCurrent = idx === clampedIndex;
            const isUpcoming = idx > clampedIndex;

            let statusClass = 'upcoming';
            if (isCompleted) statusClass = 'completed';
            if (isCurrent) statusClass = 'active';

            return (
              <div
                key={stage.number}
                className={`pipeline-step-item ${statusClass}`}
                id={`pipeline-stage-${stage.number}`}
              >
                <div className="pipeline-step-indicator">
                  {isCompleted && (
                    <span className="pipeline-step-check" title="Completed">
                      <Check size={12} strokeWidth={3} />
                    </span>
                  )}
                  {isCurrent && (
                    <span className="pipeline-step-spinner" title="In progress">
                      <Loader2 size={12} className="pipeline-spin-icon" />
                    </span>
                  )}
                  {isUpcoming && (
                    <span className="pipeline-step-num">
                      {stage.number}
                    </span>
                  )}
                </div>

                <div className="pipeline-step-content">
                  <div className="pipeline-step-title-row">
                    <span className="pipeline-step-num-text">Stage {stage.number}</span>
                    <span className="pipeline-step-name">{stage.name}</span>
                  </div>
                  <div className="pipeline-step-message">
                    {isCurrent ? (
                      <span className="pipeline-step-live-msg">{stage.loadingMessage}</span>
                    ) : isCompleted ? (
                      <span className="pipeline-step-done-msg">Completed</span>
                    ) : (
                      <span className="pipeline-step-pending-msg">{stage.shortName}</span>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default PipelineLoader;
