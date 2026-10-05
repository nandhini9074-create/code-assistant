import React from 'react';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { Copy, Check } from 'lucide-react';

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
    <div className="code-block">
      <div className="code-block-header">
        <span className="code-block-filename">{filename || language}</span>
        <button
          id={`copy-code-${filename ?? language}`}
          className="btn btn-ghost btn-sm btn-icon"
          onClick={handleCopy}
          aria-label="Copy code to clipboard"
          title="Copy"
        >
          {copied ? <Check size={13} color="var(--color-success)" /> : <Copy size={13} />}
        </button>
      </div>
      <div className="code-block-body" style={{ maxHeight }}>
        <SyntaxHighlighter
          language={language}
          style={oneDark}
          customStyle={{
            margin: 0,
            background: 'transparent',
            padding: '14px 16px',
          }}
          showLineNumbers
          lineNumberStyle={{ color: 'var(--color-text-muted)', fontSize: 11 }}
        >
          {code.trim()}
        </SyntaxHighlighter>
      </div>
    </div>
  );
};

export default CodeBlock;
