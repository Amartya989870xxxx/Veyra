/** NarrativeTypewriter.
 *
 * Renders the backend markdown narrative with:
 * 1. Rich semantic Markdown formatting (bold tags, list items, callout sections).
 * 2. Smooth ChatGPT / Claude-style streaming typewriter animation.
 * 3. Interactive toolbar: Skip/Instant reveal, Replay, and Copy to clipboard.
 * 4. Blinking cursor with prefers-reduced-motion fallback.
 */

import { useEffect, useRef, useState } from 'react';
import { Check, Copy, RotateCcw, ShieldAlert, Sparkles, Zap } from 'lucide-react';

interface NarrativeTypewriterProps {
  text: string;
  speedMs?: number; // ms per character chunk
  chunkSize?: number; // characters per tick
  autoStart?: boolean;
}

export function NarrativeTypewriter({
  text,
  speedMs = 12,
  chunkSize = 3,
  autoStart = true,
}: NarrativeTypewriterProps) {
  const [displayedLength, setDisplayedLength] = useState<number>(() => {
    // If reduced motion is requested, show full text immediately
    if (typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      return text.length;
    }
    return autoStart ? 0 : text.length;
  });
  const [isCopied, setIsCopied] = useState<boolean>(false);
  const timerRef = useRef<number | null>(null);

  // Reset when input text changes
  useEffect(() => {
    if (typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setDisplayedLength(text.length);
      return;
    }
    setDisplayedLength(0);
  }, [text]);

  // Typewriter streaming loop
  useEffect(() => {
    if (displayedLength >= text.length) {
      if (timerRef.current) window.clearTimeout(timerRef.current);
      return;
    }

    timerRef.current = window.setTimeout(() => {
      setDisplayedLength((prev) => Math.min(text.length, prev + chunkSize));
    }, speedMs);

    return () => {
      if (timerRef.current) window.clearTimeout(timerRef.current);
    };
  }, [displayedLength, text.length, speedMs, chunkSize]);

  const isTyping = displayedLength < text.length;
  const currentText = text.slice(0, displayedLength);

  const handleSkip = () => {
    if (timerRef.current) window.clearTimeout(timerRef.current);
    setDisplayedLength(text.length);
  };

  const handleReplay = () => {
    if (timerRef.current) window.clearTimeout(timerRef.current);
    setDisplayedLength(0);
  };

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setIsCopied(true);
      setTimeout(() => setIsCopied(false), 2000);
    } catch {
      // Clipboard fallback
    }
  };

  return (
    <div
      style={{
        borderRadius: 'var(--radius)',
        background: '#040711',
        border: '1px solid rgba(255, 255, 255, 0.08)',
        overflow: 'hidden',
        boxShadow: '0 4px 20px rgba(0, 0, 0, 0.4)',
      }}
    >
      {/* Header Toolbar */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: '10px 16px',
          background: 'rgba(255, 255, 255, 0.02)',
          borderBottom: '1px solid rgba(255, 255, 255, 0.06)',
          fontSize: '12px',
          fontFamily: 'var(--font-mono)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span
            style={{
              width: 7,
              height: 7,
              borderRadius: '50%',
              background: isTyping ? 'var(--brand)' : '#10b981',
              boxShadow: isTyping ? '0 0 8px var(--brand)' : '0 0 6px #10b981',
              animation: isTyping ? 'veyra-pulse 1.2s infinite ease-in-out' : 'none',
            }}
          />
          <span style={{ color: isTyping ? '#ffffff' : '#94a3b8', fontWeight: 600 }}>
            {isTyping ? 'GENERATING FORENSIC NARRATIVE…' : 'FORENSIC DOSSIER COMPILED'}
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          {isTyping ? (
            <button
              onClick={handleSkip}
              title="Instant reveal"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '4px',
                padding: '3px 8px',
                borderRadius: '4px',
                background: 'rgba(255, 255, 255, 0.06)',
                border: '1px solid rgba(255, 255, 255, 0.12)',
                color: '#ffffff',
                fontSize: '11px',
                cursor: 'pointer',
              }}
            >
              <Zap size={11} color="var(--brand)" /> Skip
            </button>
          ) : (
            <button
              onClick={handleReplay}
              title="Replay typewriter"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '4px',
                padding: '3px 8px',
                borderRadius: '4px',
                background: 'transparent',
                border: '1px solid rgba(255, 255, 255, 0.08)',
                color: '#94a3b8',
                fontSize: '11px',
                cursor: 'pointer',
              }}
            >
              <RotateCcw size={11} /> Replay
            </button>
          )}

          <button
            onClick={handleCopy}
            title="Copy markdown text"
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '4px',
              padding: '3px 8px',
              borderRadius: '4px',
              background: isCopied ? 'rgba(16, 185, 129, 0.15)' : 'transparent',
              border: `1px solid ${isCopied ? 'rgba(16, 185, 129, 0.4)' : 'rgba(255, 255, 255, 0.08)'}`,
              color: isCopied ? '#10b981' : '#94a3b8',
              fontSize: '11px',
              cursor: 'pointer',
              transition: 'all 0.15s ease',
            }}
          >
            {isCopied ? (
              <>
                <Check size={11} /> Copied
              </>
            ) : (
              <>
                <Copy size={11} /> Copy
              </>
            )}
          </button>
        </div>
      </div>

      {/* Rendered Body */}
      <div
        style={{
          padding: '20px 22px',
          display: 'grid',
          gap: '16px',
          fontSize: '14px',
          lineHeight: 1.7,
          color: '#cbd5e1',
        }}
      >
        <ParsedMarkdownContent text={currentText} isTyping={isTyping} />
      </div>
    </div>
  );
}

/* ------------------------------------------------------------- Content Parser */

function ParsedMarkdownContent({ text, isTyping }: { text: string; isTyping: boolean }) {
  if (!text.trim()) {
    return (
      <div style={{ color: '#64748b', fontStyle: 'italic', display: 'flex', alignItems: 'center', gap: '6px' }}>
        <span>Awaiting telemetry analysis</span>
        {isTyping && <BlinkingCursor />}
      </div>
    );
  }

  // Split into blocks by double newlines
  const rawBlocks = text.split('\n\n');

  return (
    <>
      {rawBlocks.map((block, idx) => {
        const isLastBlock = idx === rawBlocks.length - 1;
        return (
          <MarkdownBlock
            key={idx}
            content={block}
            isLast={isLastBlock}
            isTyping={isTyping && isLastBlock}
          />
        );
      })}
    </>
  );
}

function MarkdownBlock({
  content,
  isLast,
  isTyping,
}: {
  content: string;
  isLast: boolean;
  isTyping: boolean;
}) {
  const trimmed = content.trim();

  // 1. Incident Summary Block
  if (trimmed.startsWith('**Incident Summary:**')) {
    const body = trimmed.replace('**Incident Summary:**', '').trim();
    return (
      <div
        style={{
          padding: '14px 16px',
          borderRadius: '8px',
          background: 'rgba(37, 99, 235, 0.06)',
          border: '1px solid rgba(37, 99, 235, 0.22)',
          display: 'grid',
          gap: '6px',
        }}
      >
        <div
          style={{
            fontSize: '11px',
            fontFamily: 'var(--font-mono)',
            fontWeight: 700,
            letterSpacing: '0.08em',
            color: '#60a5fa',
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
          }}
        >
          <Sparkles size={13} color="#60a5fa" />
          INCIDENT SUMMARY
        </div>
        <div style={{ color: '#f1f5f9', fontSize: '14px' }}>
          {renderInlineMarkdown(body)}
          {isTyping && isLast && <BlinkingCursor />}
        </div>
      </div>
    );
  }

  // 2. Financial Exposure Block
  if (trimmed.startsWith('**Financial Exposure at Risk:**')) {
    const body = trimmed.replace('**Financial Exposure at Risk:**', '').trim();
    return (
      <div
        style={{
          padding: '14px 16px',
          borderRadius: '8px',
          background: 'rgba(245, 158, 11, 0.06)',
          border: '1px solid rgba(245, 158, 11, 0.22)',
          display: 'grid',
          gap: '6px',
        }}
      >
        <div
          style={{
            fontSize: '11px',
            fontFamily: 'var(--font-mono)',
            fontWeight: 700,
            letterSpacing: '0.08em',
            color: '#fbbf24',
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
          }}
        >
          <ShieldAlert size={13} color="#fbbf24" />
          FINANCIAL EXPOSURE AT RISK
        </div>
        <div style={{ color: '#f1f5f9', fontSize: '14px' }}>
          {renderInlineMarkdown(body)}
          {isTyping && isLast && <BlinkingCursor />}
        </div>
      </div>
    );
  }

  // 3. Recommended Defensive Control Block
  if (trimmed.startsWith('**Recommended Defensive Control')) {
    // extract tier if present
    const headerMatch = trimmed.match(/^\*\*Recommended Defensive Control \(([^)]+)\):\*\*/);
    const tier = headerMatch ? headerMatch[1] : 'RESTRICT';
    const body = trimmed.replace(/^\*\*Recommended Defensive Control [^:]+:\*\*/, '').trim();

    return (
      <div
        style={{
          padding: '14px 16px',
          borderRadius: '8px',
          background: 'rgba(249, 63, 40, 0.08)',
          border: '1px solid rgba(249, 63, 40, 0.3)',
          display: 'grid',
          gap: '6px',
        }}
      >
        <div
          style={{
            fontSize: '11px',
            fontFamily: 'var(--font-mono)',
            fontWeight: 700,
            letterSpacing: '0.08em',
            color: '#f93f28',
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
          }}
        >
          <ShieldAlert size={13} color="#f93f28" />
          RECOMMENDED DEFENSIVE CONTROL ({tier})
        </div>
        <div style={{ color: '#ffffff', fontSize: '14px' }}>
          {renderInlineMarkdown(body)}
          {isTyping && isLast && <BlinkingCursor />}
        </div>
      </div>
    );
  }

  // 4. Status / Telemetry Block
  if (trimmed.startsWith('**Status')) {
    return (
      <div
        style={{
          padding: '12px 16px',
          borderRadius: '8px',
          background: 'rgba(16, 185, 129, 0.06)',
          border: '1px solid rgba(16, 185, 129, 0.22)',
          color: '#e2e8f0',
          fontSize: '13px',
        }}
      >
        {renderInlineMarkdown(trimmed)}
        {isTyping && isLast && <BlinkingCursor />}
      </div>
    );
  }

  // 5. Section with Bullet Points (Why this was flagged)
  if (trimmed.includes('\n- ') || trimmed.startsWith('- ') || trimmed.startsWith('**Why this was flagged')) {
    const lines = trimmed.split('\n');
    return (
      <div style={{ display: 'grid', gap: '8px' }}>
        {lines.map((line, lIdx) => {
          const isLineLast = isLast && lIdx === lines.length - 1;
          const trimmedLine = line.trim();

          if (trimmedLine.startsWith('- ')) {
            const bulletBody = trimmedLine.slice(2);
            return (
              <div
                key={lIdx}
                style={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: '10px',
                  padding: '8px 12px',
                  borderRadius: '6px',
                  background: 'rgba(255, 255, 255, 0.02)',
                  border: '1px solid rgba(255, 255, 255, 0.05)',
                  fontSize: '13.5px',
                  color: '#cbd5e1',
                }}
              >
                <span
                  style={{
                    width: '6px',
                    height: '6px',
                    borderRadius: '50%',
                    background: '#f93f28',
                    marginTop: '8px',
                    flexShrink: 0,
                  }}
                />
                <div style={{ flex: 1 }}>
                  {renderInlineMarkdown(bulletBody)}
                  {isTyping && isLineLast && <BlinkingCursor />}
                </div>
              </div>
            );
          }

          // Header line for the list
          return (
            <div
              key={lIdx}
              style={{
                fontSize: '13px',
                fontWeight: 700,
                color: '#ffffff',
                fontFamily: 'var(--font-sans)',
                marginTop: '4px',
              }}
            >
              {renderInlineMarkdown(trimmedLine)}
              {isTyping && isLineLast && <BlinkingCursor />}
            </div>
          );
        })}
      </div>
    );
  }

  // 6. Generic Paragraph
  return (
    <p style={{ margin: 0, fontSize: '14px', color: '#cbd5e1' }}>
      {renderInlineMarkdown(trimmed)}
      {isTyping && isLast && <BlinkingCursor />}
    </p>
  );
}

/* ------------------------------------------------------------- Inline Parser */

function renderInlineMarkdown(str: string): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  const regex = /(\*\*[^*]+\*\*|\*[^*]+\*)/g;
  let lastIdx = 0;
  let match: RegExpExecArray | null;

  while ((match = regex.exec(str)) !== null) {
    if (match.index > lastIdx) {
      parts.push(str.slice(lastIdx, match.index));
    }
    const token = match[0];
    if (token.startsWith('**') && token.endsWith('**')) {
      const boldText = token.slice(2, -2);
      parts.push(
        <strong
          key={match.index}
          style={{
            color: '#ffffff',
            fontWeight: 700,
          }}
        >
          {boldText}
        </strong>,
      );
    } else if (token.startsWith('*') && token.endsWith('*')) {
      parts.push(
        <em
          key={match.index}
          style={{
            color: '#60a5fa',
            fontStyle: 'italic',
          }}
        >
          {token.slice(1, -1)}
        </em>,
      );
    }
    lastIdx = regex.lastIndex;
  }

  if (lastIdx < str.length) {
    const remainder = str.slice(lastIdx);
    // Handle currently typed half-open bold token `**...`
    if (remainder.startsWith('**')) {
      parts.push(
        <strong key={lastIdx} style={{ color: '#ffffff', fontWeight: 700 }}>
          {remainder.slice(2)}
        </strong>,
      );
    } else {
      parts.push(remainder);
    }
  }

  return parts;
}

function BlinkingCursor() {
  return (
    <span
      className="typewriter-cursor"
      style={{
        display: 'inline-block',
        width: '7px',
        height: '14px',
        background: '#f93f28',
        marginLeft: '4px',
        verticalAlign: 'middle',
        borderRadius: '1px',
        boxShadow: '0 0 8px rgba(249, 63, 40, 0.8)',
        animation: 'veyra-cursor-blink 0.8s infinite',
      }}
    />
  );
}
