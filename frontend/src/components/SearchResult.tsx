import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { SearchResponse } from '../types';
import CodeBlock from './CodeBlock';
import Box from '@mui/material/Box';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Typography from '@mui/material/Typography';
import Chip from '@mui/material/Chip';
import Divider from '@mui/material/Divider';
import Alert from '@mui/material/Alert';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableRow from '@mui/material/TableRow';
import LightbulbOutlinedIcon from '@mui/icons-material/LightbulbOutlined';
import GpsFixedIcon from '@mui/icons-material/GpsFixed';
import InsertDriveFileOutlinedIcon from '@mui/icons-material/InsertDriveFileOutlined';
import ErrorIcon from '@mui/icons-material/Error';
import CompareArrowsIcon from '@mui/icons-material/CompareArrows';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import GroupsIcon from '@mui/icons-material/Groups';
import VerifiedIcon from '@mui/icons-material/Verified';

interface Props {
  response: SearchResponse;
  query: string;
}

const intentLabel: Record<string, string> = {
  EXPLAIN: 'Explain',
  FIX_BUG: 'Fix Bug',
  OPTIMIZE: 'Optimize',
  REFACTOR: 'Refactor',
  FIND_USAGE: 'Find Usage',
  FIND_FUNCTION: 'Find Function',
  FIND_CLASS: 'Find Class',
  ARCHITECTURE: 'Architecture',
  SECURITY: 'Security',
  GENERAL: 'General',
};

// Prose wrapper for ReactMarkdown — applies MUI-like typography via sx
const ProseBox: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <Box
    sx={{
      '& p': { mb: 1, lineHeight: 1.75, color: 'text.secondary', fontSize: 14 },
      '& h1, & h2, & h3, & h4': { fontWeight: 700, mt: 2, mb: 1 },
      '& ul, & ol': { pl: 2.5, mb: 1 },
      '& li': { mb: 0.5, color: 'text.secondary', fontSize: 14 },
      '& code': {
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 12,
        bgcolor: 'hsl(222,14%,17%)',
        px: 0.75,
        py: 0.25,
        borderRadius: 0.5,
        color: 'primary.light',
      },
      '& pre': { borderRadius: 2, overflow: 'auto', mb: 1.5 },
      '& blockquote': {
        borderLeft: '3px solid',
        borderColor: 'primary.main',
        pl: 1.5,
        ml: 0,
        color: 'text.secondary',
        fontStyle: 'italic',
      },
      '& table': { width: '100%', borderCollapse: 'collapse', mb: 1.5 },
      '& th, & td': {
        p: 1,
        border: '1px solid',
        borderColor: 'divider',
        fontSize: 13,
      },
      '& th': { background: 'hsl(222,18%,9%)', fontWeight: 700 },
      '& strong': { color: 'text.primary', fontWeight: 700 },
      '& a': { color: 'primary.light' },
    }}
  >
    {children}
  </Box>
);

interface SectionProps {
  icon: React.ReactNode;
  label: string;
  children: React.ReactNode;
}

const ResultSection: React.FC<SectionProps> = ({ icon, label, children }) => (
  <Box sx={{ mb: 2.5 }}>
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, mb: 1 }}>
      <Box sx={{ color: 'primary.main', display: 'flex', fontSize: 14 }}>{icon}</Box>
      <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
        {label}
      </Typography>
    </Box>
    {children}
  </Box>
);

const SearchResult: React.FC<Props> = ({ response, query }) => {
  const label = intentLabel[response.intent] ?? response.intent;
  const targetName = response.target?.name ? String(response.target.name) : '';

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

  const cardHeader = (
    <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 2 }}>
      <Box>
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
          Query
        </Typography>
        <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
          {query}
        </Typography>
      </Box>
      <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 0.75 }}>
        <Chip
          label={label}
          size="small"
          variant="outlined"
          color="primary"
          icon={<AutoAwesomeIcon style={{ fontSize: 13 }} />}
          sx={{ fontWeight: 700, fontSize: 11 }}
        />
        {response.confidence && (
          <Typography variant="caption" color="text.secondary">
            Confidence: {response.confidence}
          </Typography>
        )}
      </Box>
    </Box>
  );

  /* Early exit */
  if (response.early_exit) {
    return (
      <Card sx={{ animation: 'fadeIn 0.3s ease', '@keyframes fadeIn': { from: { opacity: 0, transform: 'translateY(8px)' }, to: { opacity: 1, transform: 'none' } } }}>
        <CardContent>
          {cardHeader}
          <Divider sx={{ mb: 2 }} />
          <Alert
            severity="info"
            icon={<ErrorIcon />}
            variant="outlined"
          >
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {String(response.early_exit.message ?? 'No further information available.')}
            </ReactMarkdown>
          </Alert>
        </CardContent>
      </Card>
    );
  }

  /* Ambiguous candidates */
  if (response.ambiguous_candidates.length > 0) {
    return (
      <Card sx={{ animation: 'fadeIn 0.3s ease', '@keyframes fadeIn': { from: { opacity: 0, transform: 'translateY(8px)' }, to: { opacity: 1, transform: 'none' } } }}>
        <CardContent>
          {cardHeader}
          <Divider sx={{ mb: 2 }} />
          <ResultSection icon={<GroupsIcon fontSize="small" />} label="Multiple Matches Found">
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
              The symbol <strong>{response.ambiguous_candidates[0].name}</strong> exists in multiple files.
              Please refine your query with more context:
            </Typography>
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
              {response.ambiguous_candidates.map((c, i) => (
                <Card key={i} variant="outlined" sx={{ bgcolor: 'hsl(222,14%,17%)' }}>
                  <CardContent sx={{ py: 1, '&:last-child': { pb: 1 } }}>
                    <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                        <InsertDriveFileOutlinedIcon sx={{ fontSize: 14, color: 'primary.main' }} />
                        <Typography variant="caption" color="text.secondary" sx={{ fontFamily: "'JetBrains Mono', monospace" }}>
                          {c.file_path}
                        </Typography>
                      </Box>
                      {c.score != null && (
                        <Typography variant="caption" color="text.disabled">
                          score: {c.score.toFixed(3)}
                        </Typography>
                      )}
                    </Box>
                    {c.class_name && (
                      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
                        Class: {c.class_name}
                      </Typography>
                    )}
                    {c.start_line != null && (
                      <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                        Lines {c.start_line}–{c.end_line}
                      </Typography>
                    )}
                  </CardContent>
                </Card>
              ))}
            </Box>
          </ResultSection>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card
      sx={{
        animation: 'fadeIn 0.3s ease',
        '@keyframes fadeIn': { from: { opacity: 0, transform: 'translateY(8px)' }, to: { opacity: 1, transform: 'none' } },
      }}
    >
      <CardContent>
        {cardHeader}
        <Divider sx={{ mb: 2 }} />

        {/* Target */}
        {response.target && (
          <ResultSection icon={<GpsFixedIcon fontSize="small" />} label="Target">
            <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
              {targetFile && (
                <Chip
                  icon={<InsertDriveFileOutlinedIcon />}
                  label={targetFile}
                  size="small"
                  variant="outlined"
                  sx={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11 }}
                />
              )}
              {targetName && (
                <Chip
                  label={targetName}
                  size="small"
                  color="primary"
                  variant="outlined"
                  sx={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11 }}
                />
              )}
              {response.target.start_line != null && (
                <Typography variant="caption" color="text.secondary" sx={{ alignSelf: 'center' }}>
                  L{String(response.target.start_line)}–{String(response.target.end_line)}
                </Typography>
              )}
            </Box>
          </ResultSection>
        )}

        {/* Analysis */}
        {response.formatted_output && (
          <ResultSection icon={<LightbulbOutlinedIcon fontSize="small" />} label="Analysis">
            <ProseBox>
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{response.formatted_output}</ReactMarkdown>
            </ProseBox>
          </ResultSection>
        )}

        {/* Suggestion */}
        {response.suggestion && !response.formatted_output && (
          <ResultSection icon={<LightbulbOutlinedIcon fontSize="small" />} label="Suggestion">
            <ProseBox>
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{response.suggestion}</ReactMarkdown>
            </ProseBox>
          </ResultSection>
        )}

        {/* Current behavior */}
        {response.current_behavior && (
          <ResultSection icon={<ErrorIcon fontSize="small" />} label="Current Behavior">
            <ProseBox>
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{response.current_behavior}</ReactMarkdown>
            </ProseBox>
          </ResultSection>
        )}

        {/* Proposed change */}
        {response.proposed_change && (
          <ResultSection icon={<CompareArrowsIcon fontSize="small" />} label="Proposed Change">
            <ProseBox>
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{response.proposed_change}</ReactMarkdown>
            </ProseBox>
          </ResultSection>
        )}

        {/* Suggested code */}
        {response.suggested_code && (
          <ResultSection icon={<InsertDriveFileOutlinedIcon fontSize="small" />} label="Suggested Code">
            <CodeBlock code={response.suggested_code} language={lang} filename={targetFile} />
          </ResultSection>
        )}

        {/* Suggested patch */}
        {response.suggested_patch && !response.suggested_code && (
          <ResultSection icon={<CompareArrowsIcon fontSize="small" />} label="Suggested Patch">
            <CodeBlock code={response.suggested_patch} language="diff" filename="patch.diff" />
          </ResultSection>
        )}

        {/* Patch validation */}
        {response.patch_validation && (
          <ResultSection icon={<VerifiedIcon fontSize="small" />} label="Patch Validation">
            <Table size="small" sx={{ '& td': { border: 'none', py: 0.5, px: 0 } }}>
              <TableBody>
                {Object.entries(response.patch_validation).map(([k, v]) => (
                  <TableRow key={k}>
                    <TableCell><Typography variant="caption" color="text.secondary">{k}</Typography></TableCell>
                    <TableCell align="right"><Typography variant="caption" sx={{ fontWeight: 600 }}>{String(v)}</Typography></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </ResultSection>
        )}
      </CardContent>
    </Card>
  );
};

export default SearchResult;
