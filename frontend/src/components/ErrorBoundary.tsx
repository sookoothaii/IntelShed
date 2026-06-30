import { Component, type ErrorInfo, type ReactNode } from 'react';

type ErrorBoundaryProps = {
  children: ReactNode;
  /** Unique label for this boundary (e.g. "Globe", "Map", "IntelGraph") */
  name: string;
  /** Optional: switch to alternative view on crash */
  onFallback?: () => void;
  /** Max auto-retry attempts before showing manual buttons (default 3) */
  maxRetries?: number;
  /** Auto-retry delay in ms (default 3000) */
  retryDelayMs?: number;
};

type ErrorBoundaryState = {
  hasError: boolean;
  error: Error | null;
  retryCount: number;
};

/** Report frontend crash to backend telemetry endpoint (fire-and-forget). */
function reportCrash(name: string, error: Error, info: ErrorInfo): void {
  try {
    const payload = {
      component: name,
      message: error.message,
      stack: error.stack?.slice(0, 4000) ?? '',
      componentStack: info.componentStack?.slice(0, 2000) ?? '',
      url: typeof location !== 'undefined' ? location.href : '',
      timestamp: new Date().toISOString(),
    };
    const apiKey =
      typeof localStorage !== 'undefined' ? localStorage.getItem('WORLDBASE_API_KEY') || '' : '';
    fetch('/api/telemetry/frontend-error', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(apiKey ? { 'X-API-Key': apiKey } : {}),
      },
      body: JSON.stringify(payload),
      keepalive: true,
    }).catch(() => {
      /* fire-and-forget */
    });
  } catch {
    /* never crash from telemetry */
  }
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  private retryTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null, retryCount: 0 };
  }

  static getDerivedStateFromError(error: Error): Partial<ErrorBoundaryState> {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    reportCrash(this.props.name, error, info);
    this.scheduleAutoRetry();
  }

  componentWillUnmount(): void {
    if (this.retryTimer) clearTimeout(this.retryTimer);
  }

  private scheduleAutoRetry(): void {
    const maxRetries = this.props.maxRetries ?? 3;
    const delay = this.props.retryDelayMs ?? 3000;
    if (this.state.retryCount >= maxRetries) return;
    this.retryTimer = setTimeout(() => {
      this.setState((prev) => ({
        hasError: false,
        error: null,
        retryCount: prev.retryCount + 1,
      }));
    }, delay);
  }

  private handleManualRetry = (): void => {
    this.setState({ hasError: false, error: null, retryCount: 0 });
  };

  private handleSwitchView = (): void => {
    this.props.onFallback?.();
    this.setState({ hasError: false, error: null, retryCount: 0 });
  };

  render(): ReactNode {
    if (!this.state.hasError) return this.props.children;

    const name = this.props.name;
    const exhausted = this.state.retryCount >= (this.props.maxRetries ?? 3);

    return (
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          height: '100%',
          minHeight: '200px',
          gap: '12px',
          padding: '24px',
          background: '#0a0e14',
          color: '#c0c8d4',
          fontFamily: 'monospace',
          textAlign: 'center',
        }}
      >
        <div style={{ fontSize: '1.4rem', color: '#ff4d5e' }}>⚠ {name} crashed</div>
        {this.state.error && (
          <div
            style={{
              fontSize: '0.8rem',
              color: '#888',
              maxWidth: '600px',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {this.state.error.message}
          </div>
        )}
        {exhausted ? (
          <div style={{ display: 'flex', gap: '12px' }}>
            <button
              onClick={this.handleManualRetry}
              style={{
                padding: '6px 16px',
                fontSize: '0.85rem',
                background: '#1a2a3a',
                color: '#00e5a0',
                border: '1px solid #00e5a044',
                borderRadius: '4px',
                cursor: 'pointer',
              }}
            >
              ↻ Reload {name}
            </button>
            {this.props.onFallback && (
              <button
                onClick={this.handleSwitchView}
                style={{
                  padding: '6px 16px',
                  fontSize: '0.85rem',
                  background: '#1a2a3a',
                  color: '#c0c8d4',
                  border: '1px solid #333',
                  borderRadius: '4px',
                  cursor: 'pointer',
                }}
              >
                → Switch view
              </button>
            )}
          </div>
        ) : (
          <div style={{ fontSize: '0.75rem', color: '#666' }}>
            Auto-recovering… (attempt {this.state.retryCount + 1}/{this.props.maxRetries ?? 3})
          </div>
        )}
      </div>
    );
  }
}

/** Convenience wrapper: use around any component to add error isolation. */
export function withErrorBoundary(
  children: ReactNode,
  name: string,
  onFallback?: () => void,
): ReactNode {
  return (
    <ErrorBoundary name={name} onFallback={onFallback}>
      {children}
    </ErrorBoundary>
  );
}
