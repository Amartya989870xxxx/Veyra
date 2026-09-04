/** Small shared UI primitives.
 *
 * Deliberately plain: inline styles keyed off the CSS custom properties in
 * tokens.css, no component framework, no styling dependency. Everything here is
 * a semantic element (real <button>, real <table>) so keyboard and screen-reader
 * behaviour comes for free rather than being re-implemented.
 */

import React, { useId, useState } from 'react';
import { AlertTriangle, Check, ChevronDown, Info, RefreshCw } from 'lucide-react';

/* ---------------------------------------------------------------- Button */

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';

export function Button({
  children,
  variant = 'secondary',
  size = 'md',
  loading = false,
  icon,
  full = false,
  style,
  disabled,
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: 'sm' | 'md' | 'lg';
  loading?: boolean;
  icon?: React.ReactNode;
  full?: boolean;
}) {
  const pad =
    size === 'lg' ? '14px 26px' : size === 'sm' ? '6px 12px' : '10px 18px';
  const fontSize =
    size === 'lg' ? 'var(--text-md)' : size === 'sm' ? 'var(--text-sm)' : 'var(--text-base)';

  // Gradient means "this is an action". Flat colour is reserved for status, so a
  // primary button can never be mistaken for a severity badge.
  const palette: Record<ButtonVariant, React.CSSProperties> = {
    primary: {
      background: 'var(--grad-brand)',
      color: '#fff',
      border: '1px solid transparent',
      boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.22), var(--glow-brand)',
    },
    secondary: {
      background: 'var(--glass)',
      backdropFilter: 'blur(18px) saturate(140%)',
      WebkitBackdropFilter: 'blur(18px) saturate(140%)',
      color: 'var(--text-primary)',
      border: '1px solid var(--glass-edge)',
      boxShadow: 'inset 0 1px 0 var(--glass-lip)',
    },
    ghost: {
      background: 'transparent',
      color: 'var(--text-secondary)',
      border: '1px solid transparent',
    },
    danger: {
      background: 'var(--tier-restrict-wash)',
      color: 'var(--tier-restrict)',
      border: '1px solid rgba(255,67,89,0.4)',
    },
  };

  const isDisabled = disabled || loading;

  return (
    <button
      {...rest}
      disabled={isDisabled}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 'var(--sp-2)',
        padding: pad,
        width: full ? '100%' : undefined,
        fontSize,
        fontWeight: 600,
        letterSpacing: '-0.01em',
        whiteSpace: 'nowrap',
        borderRadius: 'var(--radius)',
        transition:
          'transform 0.2s var(--ease), filter 0.2s var(--ease), box-shadow 0.2s var(--ease), opacity 0.15s',
        opacity: isDisabled ? 0.55 : 1,
        cursor: isDisabled ? 'not-allowed' : 'pointer',
        ...palette[variant],
        ...style,
      }}
      onMouseEnter={(e) => {
        if (isDisabled) return;
        e.currentTarget.style.filter = 'brightness(1.1)';
        e.currentTarget.style.transform = 'translateY(-1px)';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.filter = 'none';
        e.currentTarget.style.transform = 'none';
      }}
    >
      {loading ? (
        <RefreshCw size={size === 'lg' ? 18 : 15} style={{ animation: 'veyra-spin 1s linear infinite' }} />
      ) : (
        icon
      )}
      {children}
    </button>
  );
}

/* ------------------------------------------------------------------ Card */

/** Translucent panel. The ambient colour field shows through it, which is what
 *  separates this from a flat card on a flat page — set `solid` where content
 *  legibility matters more than depth (dense tables, code). */
export function Card({
  children,
  padded = true,
  solid = false,
  style,
  ...rest
}: React.HTMLAttributes<HTMLDivElement> & { padded?: boolean; solid?: boolean }) {
  return (
    <div
      {...rest}
      className={[solid ? undefined : 'glass', rest.className].filter(Boolean).join(' ') || undefined}
      style={{
        ...(solid
          ? { background: 'var(--surface-1)', border: '1px solid var(--border-subtle)' }
          : null),
        borderRadius: 'var(--radius-lg)',
        padding: padded ? 'var(--sp-5)' : 0,
        ...style,
      }}
    >
      {children}
    </div>
  );
}

export function SectionLabel({ children }: { children: React.ReactNode }) {
  return <div className="eyebrow">{children}</div>;
}

/* ----------------------------------------------------------------- Badge */

export function Badge({
  children,
  color = 'var(--text-secondary)',
  background = 'rgba(255,255,255,0.06)',
  style,
}: {
  children: React.ReactNode;
  color?: string;
  background?: string;
  style?: React.CSSProperties;
}) {
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        padding: '4px 10px',
        borderRadius: 999,
        fontSize: 'var(--text-xs)',
        fontWeight: 600,
        letterSpacing: '0.04em',
        color,
        background,
        border: `1px solid ${color}33`,
        whiteSpace: 'nowrap',
        ...style,
      }}
    >
      {children}
    </span>
  );
}

/* --------------------------------------------------------------- Tooltip */

/** Hover/focus tooltip. Focusable so keyboard users get the same explanation. */
export function InfoTip({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <span style={{ position: 'relative', display: 'inline-flex' }}>
      <button
        type="button"
        aria-label="More information"
        aria-describedby={open ? id : undefined}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        style={{
          background: 'none',
          border: 'none',
          padding: 0,
          display: 'inline-flex',
          color: 'var(--text-muted)',
        }}
      >
        <Info size={13} />
      </button>
      {open && (
        <span
          id={id}
          role="tooltip"
          style={{
            position: 'absolute',
            bottom: 'calc(100% + 8px)',
            left: '50%',
            transform: 'translateX(-50%)',
            width: 240,
            padding: 'var(--sp-3)',
            background: 'var(--surface-3)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius)',
            fontSize: 'var(--text-xs)',
            lineHeight: 1.5,
            color: 'var(--text-secondary)',
            boxShadow: 'var(--shadow)',
            zIndex: 60,
            fontWeight: 400,
            letterSpacing: 0,
            textTransform: 'none',
          }}
        >
          {text}
        </span>
      )}
    </span>
  );
}

/* ------------------------------------------------------- Loading / error */

export function Skeleton({ height = 16, width = '100%', style }: { height?: number | string; width?: number | string; style?: React.CSSProperties }) {
  return (
    <div
      aria-hidden
      style={{
        height,
        width,
        borderRadius: 'var(--radius-sm)',
        background:
          'linear-gradient(90deg, var(--surface-2) 0%, var(--surface-3) 50%, var(--surface-2) 100%)',
        backgroundSize: '800px 100%',
        animation: 'veyra-shimmer 1.4s linear infinite',
        ...style,
      }}
    />
  );
}

export function LoadingBlock({ label, rows = 3 }: { label: string; rows?: number }) {
  return (
    <div role="status" aria-live="polite" style={{ display: 'grid', gap: 'var(--sp-3)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)', color: 'var(--text-secondary)', fontSize: 'var(--text-sm)' }}>
        <RefreshCw size={14} style={{ animation: 'veyra-spin 1s linear infinite', color: 'var(--accent-bright)' }} />
        {label}
      </div>
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} height={i === 0 ? 44 : 16} width={i === rows - 1 ? '70%' : '100%'} />
      ))}
    </div>
  );
}

export function ErrorState({
  title,
  detail,
  onRetry,
}: {
  title: string;
  detail?: string;
  onRetry?: () => void;
}) {
  return (
    <div
      role="alert"
      style={{
        display: 'grid',
        gap: 'var(--sp-3)',
        padding: 'var(--sp-5)',
        background: 'var(--tier-restrict-wash)',
        border: '1px solid rgba(244,63,94,0.28)',
        borderRadius: 'var(--radius-lg)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)', color: 'var(--tier-restrict)', fontWeight: 600 }}>
        <AlertTriangle size={16} />
        {title}
      </div>
      {detail && (
        <p style={{ color: 'var(--text-secondary)', fontSize: 'var(--text-sm)', lineHeight: 1.6 }}>{detail}</p>
      )}
      {onRetry && (
        <div>
          <Button size="sm" onClick={onRetry} icon={<RefreshCw size={13} />}>
            Try again
          </Button>
        </div>
      )}
    </div>
  );
}

export function EmptyState({
  title,
  detail,
  description,
  action,
}: {
  title: string;
  detail?: string;
  description?: string;
  action?: React.ReactNode;
}) {
  const text = detail || description;
  return (
    <div
      style={{
        display: 'grid',
        gap: 'var(--sp-3)',
        justifyItems: 'center',
        textAlign: 'center',
        padding: 'var(--sp-8) var(--sp-5)',
        border: '1px dashed var(--border)',
        borderRadius: 'var(--radius-lg)',
        color: 'var(--text-secondary)',
      }}
    >
      <div style={{ fontSize: 'var(--text-md)', fontWeight: 600, color: 'var(--text-primary)' }}>{title}</div>
      {text && <p style={{ maxWidth: 420, fontSize: 'var(--text-sm)', lineHeight: 1.6 }}>{text}</p>}
      {action}
    </div>
  );
}

/* ------------------------------------------------------------------ Tabs */

export function Tabs({
  tabs,
  active,
  onChange,
}: {
  tabs: { id: string; label: string; hint?: string }[];
  active: string;
  onChange: (id: string) => void;
}) {
  return (
    <div
      role="tablist"
      aria-label="Detection detail"
      style={{
        display: 'flex',
        gap: 4,
        borderBottom: '1px solid var(--border-subtle)',
        overflowX: 'auto',
        scrollbarWidth: 'thin',
      }}
    >
      {tabs.map((t) => {
        const selected = t.id === active;
        return (
          <button
            key={t.id}
            role="tab"
            id={`tab-${t.id}`}
            aria-selected={selected}
            aria-controls={`panel-${t.id}`}
            onClick={() => onChange(t.id)}
            style={{
              padding: '11px 16px',
              background: 'none',
              border: 'none',
              borderBottom: `2px solid ${selected ? 'var(--accent)' : 'transparent'}`,
              color: selected ? 'var(--text-primary)' : 'var(--text-secondary)',
              fontWeight: selected ? 600 : 500,
              fontSize: 'var(--text-sm)',
              whiteSpace: 'nowrap',
              transition: 'color 0.15s',
            }}
          >
            {t.label}
          </button>
        );
      })}
    </div>
  );
}

/* -------------------------------------------------------------- Disclosure */

/** Progressive disclosure: conclusions first, raw metrics behind a toggle. */
export function Disclosure({
  summary,
  children,
  defaultOpen = false,
}: {
  summary: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div style={{ border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius)', overflow: 'hidden' }}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        style={{
          width: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 'var(--sp-3)',
          padding: 'var(--sp-3) var(--sp-4)',
          background: 'var(--surface-2)',
          border: 'none',
          color: 'var(--text-secondary)',
          fontSize: 'var(--text-sm)',
          fontWeight: 500,
          textAlign: 'left',
        }}
      >
        {summary}
        <ChevronDown
          size={15}
          style={{ transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s var(--ease)', flexShrink: 0 }}
        />
      </button>
      {open && <div style={{ padding: 'var(--sp-4)', background: 'var(--bg-sunken)' }}>{children}</div>}
    </div>
  );
}

/* ------------------------------------------------------------------ Stat */

export function Stat({
  label,
  value,
  sub,
  accent,
  tip,
}: {
  label: string;
  value: React.ReactNode;
  sub?: string;
  accent?: string;
  tip?: string;
}) {
  return (
    <div style={{ display: 'grid', gap: 4 }}>
      <div className="eyebrow" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        {label}
        {tip && <InfoTip text={tip} />}
      </div>
      <div
        className="tabular"
        style={{ fontSize: 'var(--text-xl)', fontWeight: 600, color: accent ?? 'var(--text-primary)', lineHeight: 1.2 }}
      >
        {value}
      </div>
      {sub && <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>{sub}</div>}
    </div>
  );
}

export function CheckItem({ children }: { children: React.ReactNode }) {
  return (
    <li style={{ display: 'flex', gap: 'var(--sp-3)', alignItems: 'flex-start', fontSize: 'var(--text-sm)', color: 'var(--text-secondary)', lineHeight: 1.6 }}>
      <Check size={15} style={{ color: 'var(--tier-observe)', flexShrink: 0, marginTop: 3 }} />
      <span>{children}</span>
    </li>
  );
}
