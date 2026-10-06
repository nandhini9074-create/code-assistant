import React, { useState } from 'react';
import Box from '@mui/material/Box';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Typography from '@mui/material/Typography';
import LinearProgress from '@mui/material/LinearProgress';
import Chip from '@mui/material/Chip';
import Button from '@mui/material/Button';
import Collapse from '@mui/material/Collapse';
import Grid from '@mui/material/Grid';
import CircularProgress from '@mui/material/CircularProgress';
import CheckIcon from '@mui/icons-material/Check';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import AccessTimeIcon from '@mui/icons-material/AccessTime';
import VerifiedUserIcon from '@mui/icons-material/VerifiedUser';
import ExploreIcon from '@mui/icons-material/Explore';
import FilterListIcon from '@mui/icons-material/FilterList';
import StorageIcon from '@mui/icons-material/Storage';
import SearchIcon from '@mui/icons-material/Search';
import CodeIcon from '@mui/icons-material/Code';
import LayersIcon from '@mui/icons-material/Layers';
import MemoryIcon from '@mui/icons-material/Memory';
import FlashOnIcon from '@mui/icons-material/FlashOn';
import BuildIcon from '@mui/icons-material/Build';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import TaskAltIcon from '@mui/icons-material/TaskAlt';

export interface PipelineStageInfo {
  number: number;
  name: string;
  shortName: string;
  loadingMessage: string;
  detail: string;
  typicalDurationMs: number;
}

export const PIPELINE_STAGES: PipelineStageInfo[] = [
  { number: 1,  name: 'Request Validation',    shortName: 'Validation',       loadingMessage: 'Validating request query parameters and repository source...',         detail: 'Verifies query format, repository target existence, and user constraints.',                         typicalDurationMs: 700  },
  { number: 2,  name: 'Intent Classification', shortName: 'Intent',           loadingMessage: 'Classifying query intent and search strategy...',                      detail: 'Determines whether query is explain, debug, fix, search, or architectural inquiry.',               typicalDurationMs: 900  },
  { number: 3,  name: 'Query Preprocessing',   shortName: 'Preprocessing',    loadingMessage: 'Extracting keywords, function identifiers, and syntax tokens...',       detail: 'Normalizes search terms and separates natural language from code identifiers.',                    typicalDurationMs: 800  },
  { number: 4,  name: 'Collection Selection',  shortName: 'Collection',       loadingMessage: 'Selecting repository vector collection in Qdrant...',                   detail: 'Resolves repository name to active Qdrant vector database namespace.',                             typicalDurationMs: 700  },
  { number: 5,  name: 'Code Retrieval',        shortName: 'Retrieval',        loadingMessage: 'Searching vector database for matching code chunks and embeddings...',  detail: 'Performs semantic vector search against indexed AST chunks and code snippets.',                    typicalDurationMs: 1600 },
  { number: 6,  name: 'Code Identification',   shortName: 'Identification',   loadingMessage: 'Identifying primary classes, functions, and target symbols...',         detail: 'Pins exact symbol definitions and resolves any ambiguous identifier candidates.',                   typicalDurationMs: 1200 },
  { number: 7,  name: 'Context Builder',       shortName: 'Context',          loadingMessage: 'Assembling complete context window with cross-file references...',       detail: 'Builds coherent prompt context with imports, callers, and related implementations.',                typicalDurationMs: 1000 },
  { number: 8,  name: 'Code Analysis',         shortName: 'Analysis',         loadingMessage: 'Running deep semantic code analysis with AI model...',                  detail: 'LLM evaluates code logic, dependencies, control flows, and potential issues.',                    typicalDurationMs: 3500 },
  { number: 9,  name: 'Evidence Validation',   shortName: 'Evidence',         loadingMessage: 'Validating analysis evidence against actual codebase facts...',         detail: 'Ensures reasoning is strictly grounded in retrieved chunks without hallucination.',                typicalDurationMs: 1200 },
  { number: 10, name: 'Action Analysis',       shortName: 'Action Planning',  loadingMessage: 'Planning remediation actions, refactoring, and code changes...',        detail: 'Formulates concrete action plan and architectural recommendations.',                               typicalDurationMs: 1500 },
  { number: 11, name: 'Suggestion Patch',      shortName: 'Patch Gen',        loadingMessage: 'Generating suggested code modifications and unified diffs...',           detail: 'Produces precise line-by-line diffs and code patch replacements.',                                typicalDurationMs: 2200 },
  { number: 12, name: 'Suggestion Validation', shortName: 'Patch Validation', loadingMessage: 'Validating suggested patch syntax, integrity, and safety...',           detail: 'Checks patch consistency against original source code structure.',                                typicalDurationMs: 1000 },
  { number: 13, name: 'Final Triage',          shortName: 'Final Triage',     loadingMessage: 'Performing safety checks, confidence scoring, and candidate ranking...', detail: 'Ranks final recommendations and verifies security guardrails.',                                    typicalDurationMs: 900  },
  { number: 14, name: 'Response Generation',   shortName: 'Response Gen',     loadingMessage: 'Synthesizing final structured response and formatted explanation...',    detail: 'Formats answer with markdown, code highlights, and actionable suggestions.',                       typicalDurationMs: 1800 },
];

interface PipelineLoaderProps {
  currentStageIndex: number;
  elapsedSeconds: number;
}

const stageIcons: Record<number, React.ReactNode> = {
  1:  <VerifiedUserIcon fontSize="small" />,
  2:  <ExploreIcon fontSize="small" />,
  3:  <FilterListIcon fontSize="small" />,
  4:  <StorageIcon fontSize="small" />,
  5:  <SearchIcon fontSize="small" />,
  6:  <CodeIcon fontSize="small" />,
  7:  <LayersIcon fontSize="small" />,
  8:  <MemoryIcon fontSize="small" />,
  9:  <VerifiedUserIcon fontSize="small" />,
  10: <FlashOnIcon fontSize="small" />,
  11: <BuildIcon fontSize="small" />,
  12: <CheckCircleOutlineIcon fontSize="small" />,
  13: <AutoAwesomeIcon fontSize="small" />,
  14: <TaskAltIcon fontSize="small" />,
};

export const PipelineLoader: React.FC<PipelineLoaderProps> = ({ currentStageIndex, elapsedSeconds }) => {
  const [showAllStages, setShowAllStages] = useState(true);

  const totalStages = PIPELINE_STAGES.length;
  const clampedIndex = Math.min(Math.max(currentStageIndex, 0), totalStages - 1);
  const activeStage = PIPELINE_STAGES[clampedIndex];
  const progressPercent = Math.min(Math.round(((clampedIndex + 0.6) / totalStages) * 100), 98);

  return (
    <Card
      role="region"
      aria-label="Search pipeline progress"
      sx={{
        position: 'relative',
        overflow: 'hidden',
        '&::before': {
          content: '""',
          position: 'absolute',
          inset: 0,
          background: 'radial-gradient(ellipse at top left, hsla(258,90%,66%,0.06) 0%, transparent 60%)',
          pointerEvents: 'none',
        },
      }}
    >
      <CardContent>
        {/* Header */}
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 2.5 }}>
          <Box>
            <Chip
              label="PIPELINE RUNNING"
              size="small"
              color="primary"
              variant="outlined"
              icon={<Box component="span" sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: 'primary.main', animation: 'pulseDot 1.5s ease-in-out infinite', '@keyframes pulseDot': { '0%,100%': { opacity: 1 }, '50%': { opacity: 0.3 } }, ml: 0.5 }} />}
              sx={{ mb: 1, fontWeight: 700, fontSize: 10, letterSpacing: '0.06em' }}
            />
            <Typography variant="h6" fontWeight={700} gutterBottom>
              Executing Deep Search Pipeline
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Analyzing repository semantics, extracting references, and generating insights
            </Typography>
          </Box>
          <Box sx={{ display: 'flex', gap: 1, flexShrink: 0 }}>
            <Chip
              icon={<AccessTimeIcon />}
              label={`${elapsedSeconds.toFixed(1)}s`}
              size="small"
              variant="outlined"
              sx={{ fontWeight: 600 }}
            />
            <Chip
              label={`Stage ${activeStage.number}/${totalStages}`}
              size="small"
              color="primary"
              sx={{ fontWeight: 700 }}
            />
          </Box>
        </Box>

        {/* Progress bar */}
        <Box sx={{ mb: 2 }}>
          <LinearProgress
            variant="determinate"
            value={progressPercent}
            sx={{ mb: 0.75 }}
          />
          <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
            <Typography variant="caption" color="text.secondary">
              Step {activeStage.number} — {activeStage.name}
            </Typography>
            <Typography variant="caption" color="primary.main" fontWeight={700}>
              {progressPercent}%
            </Typography>
          </Box>
        </Box>

        {/* Active stage card */}
        <Box
          sx={{
            p: 2,
            mb: 2,
            borderRadius: 2,
            bgcolor: 'hsl(222,14%,17%)',
            border: '1px solid',
            borderColor: 'hsla(258,90%,66%,0.25)',
            display: 'flex',
            alignItems: 'flex-start',
            gap: 2,
          }}
        >
          <Box
            sx={{
              width: 44,
              height: 44,
              borderRadius: 2,
              background: 'linear-gradient(135deg, hsla(258,90%,66%,0.2), hsla(258,70%,55%,0.2))',
              border: '1px solid hsla(258,90%,66%,0.3)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
              color: 'primary.main',
            }}
          >
            {stageIcons[activeStage.number] ?? <CircularProgress size={20} />}
          </Box>
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
              <Chip
                label={`STAGE ${String(activeStage.number).padStart(2, '0')}`}
                size="small"
                sx={{ fontSize: 10, fontWeight: 700, bgcolor: 'hsla(258,90%,66%,0.15)', color: 'primary.light' }}
              />
              <Typography variant="body2" fontWeight={700}>
                {activeStage.name}
              </Typography>
            </Box>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.75 }}>
              <CircularProgress size={14} sx={{ color: 'primary.main', flexShrink: 0 }} />
              <Typography variant="body2" color="text.secondary" sx={{ fontSize: 13 }}>
                {activeStage.loadingMessage}
              </Typography>
            </Box>
            <Typography variant="caption" color="text.disabled">
              {activeStage.detail}
            </Typography>
          </Box>
        </Box>

        {/* Toggle stages */}
        <Box sx={{ display: 'flex', justifyContent: 'center', mb: showAllStages ? 2 : 0 }}>
          <Button
            size="small"
            variant="text"
            color="inherit"
            endIcon={showAllStages ? <ExpandLessIcon /> : <ExpandMoreIcon />}
            onClick={() => setShowAllStages((v) => !v)}
            aria-expanded={showAllStages}
            sx={{ color: 'text.secondary', fontSize: 12 }}
          >
            {showAllStages ? 'Hide full stage breakdown' : 'Show all 14 pipeline stages'}
          </Button>
        </Box>

        {/* All stages grid */}
        <Collapse in={showAllStages}>
          <Grid container spacing={1}>
            {PIPELINE_STAGES.map((stage, idx) => {
              const isCompleted = idx < clampedIndex;
              const isCurrent = idx === clampedIndex;
              const isUpcoming = idx > clampedIndex;

              return (
                <Grid
                  key={stage.number}
                  size={{ xs: 12, sm: 6, md: 4, lg: 3 }}
                >
                  <Box
                    id={`pipeline-stage-${stage.number}`}
                    sx={{
                      p: 1.25,
                      borderRadius: 1.5,
                      border: '1px solid',
                      borderColor: isCurrent
                        ? 'hsla(258,90%,66%,0.4)'
                        : isCompleted
                        ? 'hsla(145,70%,50%,0.25)'
                        : 'divider',
                      bgcolor: isCurrent
                        ? 'hsla(258,90%,66%,0.08)'
                        : isCompleted
                        ? 'hsla(145,70%,50%,0.05)'
                        : 'transparent',
                      display: 'flex',
                      alignItems: 'flex-start',
                      gap: 1,
                      transition: 'all 0.2s ease',
                      opacity: isUpcoming ? 0.5 : 1,
                    }}
                  >
                    {/* Indicator */}
                    <Box sx={{ flexShrink: 0, mt: 0.25 }}>
                      {isCompleted && (
                        <Box
                          sx={{
                            width: 18,
                            height: 18,
                            borderRadius: '50%',
                            bgcolor: 'success.main',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                          }}
                        >
                          <CheckIcon sx={{ fontSize: 11, color: '#000' }} />
                        </Box>
                      )}
                      {isCurrent && (
                        <CircularProgress size={18} thickness={5} sx={{ color: 'primary.main' }} />
                      )}
                      {isUpcoming && (
                        <Box
                          sx={{
                            width: 18,
                            height: 18,
                            borderRadius: '50%',
                            border: '2px solid',
                            borderColor: 'divider',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                          }}
                        >
                          <Typography sx={{ fontSize: 10, fontWeight: 700, color: 'text.disabled', lineHeight: 1 }}>
                            {stage.number}
                          </Typography>
                        </Box>
                      )}
                    </Box>

                    {/* Content */}
                    <Box sx={{ minWidth: 0 }}>
                      <Typography variant="caption" color="text.disabled" display="block" sx={{ fontSize: 10 }}>
                        Stage {stage.number}
                      </Typography>
                      <Typography
                        variant="caption"
                        fontWeight={isCurrent ? 700 : 500}
                        color={isCurrent ? 'primary.light' : isCompleted ? 'success.main' : 'text.secondary'}
                        display="block"
                        sx={{ lineHeight: 1.3 }}
                      >
                        {stage.name}
                      </Typography>
                      <Typography variant="caption" color="text.disabled" sx={{ fontSize: 10 }}>
                        {isCurrent ? 'In progress…' : isCompleted ? 'Completed' : stage.shortName}
                      </Typography>
                    </Box>
                  </Box>
                </Grid>
              );
            })}
          </Grid>
        </Collapse>
      </CardContent>
    </Card>
  );
};

export default PipelineLoader;
