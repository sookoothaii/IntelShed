import { useMemo, useState } from 'react';
import {
  OSINT_CATEGORIES,
  OSINT_TOOLS,
  buildOsintToolLinks,
  parseOsintContext,
  type OsintContext,
  type OsintStackRelation,
} from '../lib/osintToolkit';
import { OsintContextPreview } from './OsintExternalLinks';

const RELATION_LABEL: Record<OsintStackRelation, string> = {
  native: 'IN STACK',
  complement: 'COMPLEMENT',
  'link-only': 'LINK OUT',
  reference: 'REFERENCE',
};

function openUrl(url: string) {
  if (url.startsWith('/')) {
    window.open(`${window.location.origin}${url}`, '_blank', 'noopener,noreferrer');
  } else {
    window.open(url, '_blank', 'noopener,noreferrer');
  }
}

export default function OsintReferencePanel() {
  const [latInput, setLatInput] = useState('');
  const [lonInput, setLonInput] = useState('');
  const [icaoInput, setIcaoInput] = useState('');
  const [mmsiInput, setMmsiInput] = useState('');
  const [domainInput, setDomainInput] = useState('');
  const [userInput, setUserInput] = useState('');
  const [filter, setFilter] = useState('');
  const [showPreview, setShowPreview] = useState(false);

  const manualCtx = useMemo((): OsintContext => {
    const lat = latInput.trim() ? Number(latInput) : undefined;
    const lon = lonInput.trim() ? Number(lonInput) : undefined;
    return {
      lat: Number.isFinite(lat!) ? lat : undefined,
      lon: Number.isFinite(lon!) ? lon : undefined,
      icao: icaoInput.trim().toLowerCase() || undefined,
      hex: icaoInput.trim().toLowerCase() || undefined,
      mmsi: mmsiInput.trim() || undefined,
      domain: domainInput.trim() || undefined,
      username: userInput.trim() || undefined,
      zoom: 11,
    };
  }, [latInput, lonInput, icaoInput, mmsiInput, domainInput, userInput]);

  const q = filter.trim().toLowerCase();
  const filteredTools = useMemo(() => {
    if (!q) return OSINT_TOOLS;
    return OSINT_TOOLS.filter(
      (t) =>
        t.label.toLowerCase().includes(q) ||
        t.description.toLowerCase().includes(q) ||
        t.stackNote.toLowerCase().includes(q) ||
        t.tags.some((tag) => tag.includes(q)),
    );
  }, [q]);

  const stats = useMemo(() => {
    const links = buildOsintToolLinks(manualCtx);
    const contextual = links.filter((l) => l.contextual).length;
    return { total: OSINT_TOOLS.length, contextual };
  }, [manualCtx]);

  return (
    <div className="osint-ref-panel">
      <div className="osint-ref-intro">
        <p>
          Operator toolkit catalog — {stats.total} tools. WorldBase keeps live feeds in the globe
          and briefing; everything here opens in a <strong>new tab</strong> (no scraping, no TOS
          risk).
        </p>
        <ul className="osint-ref-legend">
          <li>
            <span className="osint-rel osint-rel--native">IN STACK</span> — already wired (API /
            layer)
          </li>
          <li>
            <span className="osint-rel osint-rel--complement">COMPLEMENT</span> — richer UI for same
            domain
          </li>
          <li>
            <span className="osint-rel osint-rel--link">LINK OUT</span> — external only
          </li>
          <li>
            <span className="osint-rel osint-rel--ref">REFERENCE</span> — manuals / wikis
          </li>
        </ul>
      </div>

      <div className="osint-ref-builder">
        <div className="osint-ref-builder-head">BUILD CONTEXT LINKS</div>
        <p className="osint-ref-builder-hint">
          Enter coordinates or identifiers — preview deep-links before opening. Leave blank for home
          pages only.
        </p>
        <div className="osint-ref-builder-grid">
          <label>
            LAT
            <input
              value={latInput}
              onChange={(e) => setLatInput(e.target.value)}
              placeholder="13.7563"
            />
          </label>
          <label>
            LON
            <input
              value={lonInput}
              onChange={(e) => setLonInput(e.target.value)}
              placeholder="100.5018"
            />
          </label>
          <label>
            ICAO/HEX
            <input
              value={icaoInput}
              onChange={(e) => setIcaoInput(e.target.value)}
              placeholder="8963f0"
            />
          </label>
          <label>
            MMSI
            <input
              value={mmsiInput}
              onChange={(e) => setMmsiInput(e.target.value)}
              placeholder="567123456"
            />
          </label>
          <label>
            DOMAIN
            <input
              value={domainInput}
              onChange={(e) => setDomainInput(e.target.value)}
              placeholder="example.com"
            />
          </label>
          <label>
            USERNAME
            <input
              value={userInput}
              onChange={(e) => setUserInput(e.target.value)}
              placeholder="handle"
            />
          </label>
        </div>
        <div className="osint-ref-builder-actions">
          <button type="button" className="refresh-btn" onClick={() => setShowPreview((v) => !v)}>
            {showPreview ? 'HIDE LINK PREVIEW' : `PREVIEW LINKS (${stats.contextual} contextual)`}
          </button>
          <button
            type="button"
            className="refresh-btn"
            onClick={() => {
              setLatInput('');
              setLonInput('');
              setIcaoInput('');
              setMmsiInput('');
              setDomainInput('');
              setUserInput('');
            }}
          >
            CLEAR
          </button>
        </div>
        {showPreview && <OsintContextPreview ctx={manualCtx} />}
      </div>

      <div className="osint-ref-search">
        <input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter tools (tag, name, stack note)…"
        />
      </div>

      {OSINT_CATEGORIES.map((cat) => {
        const tools = filteredTools.filter((t) => t.category === cat.id);
        if (!tools.length) return null;
        return (
          <section key={cat.id} className="osint-ref-section">
            <header className="osint-ref-section-head">
              <h3>{cat.label}</h3>
              <span className="osint-ref-count">{tools.length}</span>
            </header>
            <p className="osint-ref-blurb">{cat.blurb}</p>
            <div className="osint-ref-cards">
              {tools.map((tool) => {
                const ctx = parseOsintContext({
                  ...manualCtx,
                  lines: manualCtx.domain
                    ? [`QUERY: ${manualCtx.domain}`]
                    : manualCtx.username
                      ? [`QUERY: ${manualCtx.username}`, `TOOL: username`]
                      : manualCtx.icao
                        ? [`ICAO24: ${manualCtx.icao}`]
                        : manualCtx.mmsi
                          ? [`MMSI: ${manualCtx.mmsi}`]
                          : manualCtx.lat != null && manualCtx.lon != null
                            ? [`LAT/LON: ${manualCtx.lat}, ${manualCtx.lon}`]
                            : [],
                });
                const built = tool.buildUrl?.(ctx) || tool.homeUrl;
                const contextual = Boolean(tool.buildUrl?.(ctx) && built !== tool.homeUrl);
                return (
                  <article key={tool.id} className="osint-ref-card">
                    <div className="osint-ref-card-top">
                      <span
                        className={`osint-rel osint-rel--${tool.stackRelation === 'link-only' ? 'link' : tool.stackRelation === 'reference' ? 'ref' : tool.stackRelation}`}
                      >
                        {RELATION_LABEL[tool.stackRelation]}
                      </span>
                      {contextual && <span className="osint-ext-link-badge">CTX</span>}
                    </div>
                    <h4>{tool.label}</h4>
                    <p className="osint-ref-desc">{tool.description}</p>
                    <p className="osint-ref-stack">{tool.stackNote}</p>
                    <div className="osint-ref-tags">
                      {tool.tags.map((tag) => (
                        <span key={tag} className="osint-ref-tag">
                          {tag}
                        </span>
                      ))}
                    </div>
                    <button type="button" className="osint-ref-open" onClick={() => openUrl(built)}>
                      OPEN {contextual ? 'CONTEXT LINK' : 'HOME'} ↗
                    </button>
                  </article>
                );
              })}
            </div>
          </section>
        );
      })}

      <footer className="osint-ref-footer">
        <p>
          Catalog: {OSINT_TOOLS.length} tools across {OSINT_CATEGORIES.length} categories (native +
          Tier A/B link-out).
        </p>
        <p>
          <strong>S2U Map:</strong> set <code>VITE_S2U_MAP_URL</code> in <code>frontend/.env</code>{' '}
          for your ArcGIS Experience URL.
        </p>
        <p>
          <strong>Backend enrich:</strong> <code>/api/osint/domain</code> adds crt.sh subdomains;{' '}
          <code>/api/osint/email</code> adds HIBP when <code>HIBP_API_KEY</code> is set in{' '}
          <code>backend/.env</code>.
        </p>
        <p>
          <strong>Do not ingest</strong> LiveUAMap, Downdetector, FR24, or Shodan into briefing —
          link-out keeps licenses clean.
        </p>
      </footer>
    </div>
  );
}
