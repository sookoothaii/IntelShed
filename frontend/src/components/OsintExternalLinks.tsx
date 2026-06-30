import { useMemo, useState } from 'react';
import {
  buildOsintToolLinks,
  OSINT_CATEGORIES,
  parseOsintContext,
  type OsintContext,
  type OsintToolLink,
} from '../lib/osintToolkit';

function openUrl(url: string) {
  if (url.startsWith('/')) {
    window.open(`${window.location.origin}${url}`, '_blank', 'noopener,noreferrer');
  } else {
    window.open(url, '_blank', 'noopener,noreferrer');
  }
}

function LinkButton({ link, compact }: { link: OsintToolLink; compact?: boolean }) {
  return (
    <button
      type="button"
      className={`osint-ext-link${link.contextual ? ' osint-ext-link--ctx' : ''}${compact ? ' osint-ext-link--compact' : ''}`}
      title={`${link.description}\n\nStack: ${link.stackNote}`}
      onClick={() => openUrl(link.url)}
    >
      <span className="osint-ext-link-label">{link.label}</span>
      {link.contextual && <span className="osint-ext-link-badge">CTX</span>}
      <span className="osint-ext-link-arrow" aria-hidden>
        ↗
      </span>
    </button>
  );
}

export default function OsintExternalLinks({
  kind,
  title,
  lines,
  lat,
  lon,
  maxInitial = 10,
}: {
  kind?: string;
  title?: string;
  lines?: string[];
  lat?: number;
  lon?: number;
  maxInitial?: number;
}) {
  const [expanded, setExpanded] = useState(false);

  const ctx = useMemo(
    () => parseOsintContext({ kind, title, lines, lat, lon }),
    [kind, title, lines, lat, lon],
  );

  const links = useMemo(() => buildOsintToolLinks(ctx), [ctx]);
  const contextual = links.filter((l) => l.contextual || l.relevance >= 35);
  const top = expanded ? links : links.slice(0, maxInitial);
  const hasMore = links.length > maxInitial;

  if (!links.length) return null;

  return (
    <div className="osint-ext-links">
      <div className="osint-ext-links-head">
        <span className="osint-ext-links-title">EXTERNAL OSINT</span>
        {ctx.lat != null && ctx.lon != null && (
          <span className="osint-ext-links-coords">
            {ctx.lat.toFixed(4)}°, {ctx.lon.toFixed(4)}°
          </span>
        )}
      </div>

      {contextual.length > 0 && !expanded && (
        <div className="osint-ext-links-section">
          <div className="osint-ext-links-sub">CONTEXTUAL</div>
          <div className="osint-ext-links-grid">
            {contextual.slice(0, 6).map((l) => (
              <LinkButton key={l.id} link={l} compact />
            ))}
          </div>
        </div>
      )}

      <div className="osint-ext-links-section">
        {!expanded && contextual.length > 0 && <div className="osint-ext-links-sub">ALL TOOLS</div>}
        <div className="osint-ext-links-grid">
          {(expanded
            ? top
            : top.filter((l) => !contextual.slice(0, 6).some((c) => c.id === l.id))
          ).map((l) => (
            <LinkButton key={`all-${l.id}`} link={l} compact />
          ))}
        </div>
      </div>

      {hasMore && (
        <button
          type="button"
          className="osint-ext-links-more"
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? 'SHOW LESS' : `SHOW ALL ${links.length} TOOLS`}
        </button>
      )}
    </div>
  );
}

/** Standalone context builder for the reference panel. */
export function OsintContextPreview({ ctx }: { ctx: OsintContext }) {
  const links = useMemo(() => buildOsintToolLinks(ctx), [ctx]);
  const byCat = useMemo(() => {
    const m = new Map<string, OsintToolLink[]>();
    for (const cat of OSINT_CATEGORIES) m.set(cat.id, []);
    for (const l of links) m.get(l.category)?.push(l);
    return m;
  }, [links]);

  return (
    <div className="osint-ref-preview">
      {OSINT_CATEGORIES.map((cat) => {
        const items = byCat.get(cat.id) || [];
        if (!items.length) return null;
        return (
          <div key={cat.id} className="osint-ref-cat-block">
            <div className="osint-ref-cat-head">{cat.label}</div>
            <div className="osint-ext-links-grid">
              {items.map((l) => (
                <LinkButton key={l.id} link={l} />
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
