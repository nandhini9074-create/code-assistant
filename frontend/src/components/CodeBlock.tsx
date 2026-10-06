import React from 'react';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
import Box from '@mui/material/Box';
import IconButton from '@mui/material/IconButton';
import Typography from '@mui/material/Typography';
import Tooltip from '@mui/material/Tooltip';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import CheckIcon from '@mui/icons-material/Check';

interface Props {
  code: string;
  language?: string;
  filename?: string;
  maxHeight?: number;
}

const CodeBlock: React.FC<Props> = ({ code, language = 'python', filename, maxHeight = 400 }) => {
  const [copied, setCopied] = React.useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <Box
      sx={{
        borderRadius: 2,
        overflow: 'hidden',
        border: '1px solid',
        borderColor: 'divider',
        bgcolor: 'hsl(222, 20%, 6%)',
      }}
    >
      {/* Header */}
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          px: 2,
          py: 0.75,
          bgcolor: 'hsl(222, 18%, 9%)',
          borderBottom: '1px solid',
          borderColor: 'divider',
        }}
      >
        <Typography
          variant="caption"
          sx={{
            fontFamily: "'JetBrains Mono', monospace",
            color: 'text.secondary',
            fontSize: 11,
          }}
        >
          {filename || language}
        </Typography>
        <Tooltip title={copied ? 'Copied!' : 'Copy code'}>
          <IconButton
            id={`copy-code-${filename ?? language}`}
            size="small"
            onClick={handleCopy}
            aria-label="Copy code to clipboard"
            sx={{ color: copied ? 'success.main' : 'text.secondary' }}
          >
            {copied ? <CheckIcon fontSize="small" /> : <ContentCopyIcon fontSize="small" />}
          </IconButton>
        </Tooltip>
      </Box>

      {/* Code body */}
      <Box sx={{ maxHeight, overflowY: 'auto' }}>
        <SyntaxHighlighter
          language={language}
          style={oneDark}
          customStyle={{
            margin: 0,
            background: 'transparent',
            padding: '14px 16px',
            fontSize: 13,
          }}
          showLineNumbers
          lineNumberStyle={{ color: 'hsl(220,10%,35%)', fontSize: 11 }}
        >
          {code.trim()}
        </SyntaxHighlighter>
      </Box>
    </Box>
  );
};

export default CodeBlock;
