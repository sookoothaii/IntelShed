import { useState, useEffect, useCallback } from 'react';
import {
  searchDarkweb,
  searchDarkwebEntities,
  ingestDarkweb,
  getDarkwebStatus,
  getDarkwebEngines,
  getDarkwebMentions,
  getRansomwareGroups,
  getRansomwareVictims,
  refreshRansomware,
  ingestRansomwareVictims,
  scrapeDarkwebUrl,
  deepSearchDarkweb,
  checkEmailBreach,
  checkPasswordBreach,
  getBreachMonitors,
  removeBreachMonitor,
  refreshBreachMonitors,
  type DarkwebResult,
  type DarkwebEngineInfo,
  type DarkwebMention,
  type BreachInfo,
  type BreachMonitor,
} from '../lib/darkwebApi';

export default function DarkwebPanel() {
  const [query, setQuery] = useState('');
  const [engines, setEngines] = useState('');
  const [mode, setMode] = useState<'auto' | 'clear' | 'tor'>('auto');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<DarkwebResult[]>([]);
  const [matches, setMatches] = useState<
    Array<{
      result: DarkwebResult;
      entity_ids: string[];
      matched_names: string[];
    }>
  >([]);
  const [mentions, setMentions] = useState<DarkwebMention[]>([]);
  const [status, setStatus] = useState<{
    enabled: boolean;
    engines: string[];
    modes?: string[];
    tor_proxy: string | null;
  } | null>(null);
  const [engineList, setEngineList] = useState<DarkwebEngineInfo[]>([]);
  const [activeTab, setActiveTab] = useState<
    'search' | 'browse' | 'deep' | 'mentions' | 'ransomware' | 'breach'
  >('search');
  const [ransomwareGroups, setRansomwareGroups] = useState<
    Array<{
      name: string;
      url: string;
      tor_url: string;
      description: string;
      source: string;
      active: boolean;
    }>
  >([]);
  const [selectedRansomwareGroup, setSelectedRansomwareGroup] = useState('');
  const [ransomwareVictims, setRansomwareVictims] = useState<
    Array<{
      victim: string;
      group: string;
      discovered?: string;
      published?: string;
      country?: string;
      activity?: string;
      description?: string;
      post_url?: string;
      website?: string;
      screenshot?: string;
      source: string;
    }>
  >([]);
  const [ransomwareLoading, setRansomwareLoading] = useState(false);
  const [breachEmail, setBreachEmail] = useState('');
  const [breachPassword, setBreachPassword] = useState('');
  const [breachLoading, setBreachLoading] = useState(false);
  const [breachResult, setBreachResult] = useState<{
    email: string;
    breached: boolean;
    breaches: BreachInfo[];
    count: number;
    error?: string;
  } | null>(null);
  const [breachPasswordResult, setBreachPasswordResult] = useState<{
    compromised: boolean;
    count: number;
    error?: string;
  } | null>(null);
  const [breachMonitors, setBreachMonitors] = useState<BreachMonitor[]>([]);
  const [breachRefreshResult, setBreachRefreshResult] = useState<{
    checked: number;
    new_breaches: number;
  } | null>(null);
  const [browseUrl, setBrowseUrl] = useState('');
  const [browseLoading, setBrowseLoading] = useState(false);
  const [browseResult, setBrowseResult] = useState<{
    url: string;
    ok: boolean;
    error?: string;
    text: string;
    entities: Record<string, string[]>;
  } | null>(null);
  const [browseHistory, setBrowseHistory] = useState<string[]>([]);
  const [deepLoading, setDeepLoading] = useState(false);
  const [deepResults, setDeepResults] = useState<
    Array<{
      result: DarkwebResult;
      scrape: { ok: boolean; error?: string; text: string; entities: Record<string, string[]> };
      entity_ids: string[];
      matched_names: string[];
    }>
  >([]);
  const [deepQuery, setDeepQuery] = useState('');
  const [deepScrapeLimit, setDeepScrapeLimit] = useState(3);

  const loadStatus = useCallback(async () => {
    try {
      const [s, e] = await Promise.all([getDarkwebStatus(), getDarkwebEngines()]);
      setStatus(s);
      setEngines(s.engines.join(','));
      setEngineList(e.engines);
    } catch {
      setStatus({ enabled: false, engines: [], tor_proxy: null });
    }
  }, []);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  const loadMentions = useCallback(async () => {
    try {
      const data = await getDarkwebMentions(50);
      setMentions(data.mentions || []);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    if (activeTab === 'mentions') loadMentions();
  }, [activeTab, loadMentions]);

  const loadRansomwareGroups = useCallback(async () => {
    try {
      setRansomwareLoading(true);
      const data = await getRansomwareGroups();
      setRansomwareGroups(data.groups || []);
    } catch {
      setRansomwareGroups([]);
    } finally {
      setRansomwareLoading(false);
    }
  }, []);

  const loadRansomwareVictims = async (groupId: string) => {
    if (!groupId) return;
    setRansomwareLoading(true);
    setError(null);
    try {
      const data = await getRansomwareVictims(groupId, 50);
      setRansomwareVictims(data.victims || []);
    } catch (e) {
      setError((e as Error).message);
      setRansomwareVictims([]);
    } finally {
      setRansomwareLoading(false);
    }
  };

  const handleRefreshRansomware = async () => {
    setRansomwareLoading(true);
    setError(null);
    try {
      await refreshRansomware();
      await loadRansomwareGroups();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRansomwareLoading(false);
    }
  };

  const handleIngestRansomware = async () => {
    if (!selectedRansomwareGroup) return;
    setRansomwareLoading(true);
    setError(null);
    try {
      await ingestRansomwareVictims(selectedRansomwareGroup, 50);
      await loadMentions();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRansomwareLoading(false);
    }
  };

  useEffect(() => {
    if (activeTab === 'ransomware') loadRansomwareGroups();
  }, [activeTab, loadRansomwareGroups]);

  useEffect(() => {
    if (selectedRansomwareGroup) {
      loadRansomwareVictims(selectedRansomwareGroup);
    }
  }, [selectedRansomwareGroup]);

  const loadBreachMonitors = useCallback(async () => {
    try {
      const data = await getBreachMonitors();
      setBreachMonitors(data.monitors || []);
    } catch {
      setBreachMonitors([]);
    }
  }, []);

  const handleBreachCheck = async () => {
    if (!breachEmail.trim()) return;
    setBreachLoading(true);
    setError(null);
    setBreachResult(null);
    try {
      const data = await checkEmailBreach(breachEmail, true);
      setBreachResult(data);
      await loadBreachMonitors();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBreachLoading(false);
    }
  };

  const handlePasswordCheck = async () => {
    if (!breachPassword.trim()) return;
    setBreachLoading(true);
    setError(null);
    setBreachPasswordResult(null);
    try {
      const data = await checkPasswordBreach(breachPassword);
      setBreachPasswordResult(data);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBreachLoading(false);
    }
  };

  const handleBreachRefresh = async () => {
    setBreachLoading(true);
    setError(null);
    setBreachRefreshResult(null);
    try {
      const data = await refreshBreachMonitors();
      setBreachRefreshResult({ checked: data.checked, new_breaches: data.new_breaches });
      await loadBreachMonitors();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBreachLoading(false);
    }
  };

  const handleRemoveMonitor = async (monitorId: number) => {
    try {
      await removeBreachMonitor(monitorId);
      await loadBreachMonitors();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  useEffect(() => {
    if (activeTab === 'breach') loadBreachMonitors();
  }, [activeTab, loadBreachMonitors]);

  const handleSearch = async () => {
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const [searchData, entityData] = await Promise.all([
        searchDarkweb(query.trim(), engines, 50, false, mode),
        searchDarkwebEntities(query.trim(), engines, 50, mode),
      ]);
      setResults(searchData.results || []);
      setMatches(entityData.matches || []);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleBrowse = async (url?: string) => {
    const target = (url || browseUrl).trim();
    if (!target) return;
    setBrowseLoading(true);
    setError(null);
    setBrowseResult(null);
    try {
      const data = await scrapeDarkwebUrl(target, true);
      setBrowseResult(data);
      if (data.ok && !browseHistory.includes(target)) {
        setBrowseHistory((prev) => [target, ...prev].slice(0, 10));
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBrowseLoading(false);
    }
  };

  const openInBrowse = (url: string) => {
    setBrowseUrl(url);
    setActiveTab('browse');
    handleBrowse(url);
  };

  const handleDeepSearch = async () => {
    const q = deepQuery.trim();
    if (!q) return;
    setDeepLoading(true);
    setError(null);
    setDeepResults([]);
    try {
      const data = await deepSearchDarkweb(q, engines, 20, deepScrapeLimit, mode);
      setDeepResults(data.matches || []);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setDeepLoading(false);
    }
  };

  const handleIngest = async (q?: string) => {
    const target = (q || query).trim();
    if (!target) return;
    setLoading(true);
    setError(null);
    try {
      await ingestDarkweb(target, engines, 50, mode);
      await loadMentions();
      setActiveTab('mentions');
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const renderEngineBadges = () => (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 8 }}>
      {engineList.map((e) => {
        const configured = status?.engines.includes(e.name);
        return (
          <span
            key={e.name}
            title={`${e.url} ${e.tor_required ? '(requires Tor proxy)' : ''}`}
            style={{
              padding: '2px 6px',
              borderRadius: 4,
              fontSize: 11,
              border: `1px solid ${configured ? '#00e5a0' : '#6f8c84'}`,
              color: configured ? '#00e5a0' : '#b0c4bf',
              opacity: e.tor_required ? 0.8 : 1,
            }}
          >
            {e.name}
            {e.tor_required && ' ⚡'}
          </span>
        );
      })}
    </div>
  );

  return (
    <div style={{ padding: 12, height: '100%', overflow: 'auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <h2 style={{ margin: 0, fontSize: 16, color: '#00e5a0' }}>DARK WEB / DARKNET</h2>
        <span
          style={{
            padding: '2px 6px',
            borderRadius: 4,
            fontSize: 11,
            background: status?.enabled ? '#00e5a022' : '#ff4d5e22',
            color: status?.enabled ? '#00e5a0' : '#ff4d5e',
          }}
        >
          {status?.enabled ? 'ENABLED' : 'DISABLED'}
        </span>
        {status?.tor_proxy && (
          <span style={{ fontSize: 11, color: '#ffd23f' }}>Tor: {status.tor_proxy}</span>
        )}
      </div>

      {renderEngineBadges()}

      <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
        <button
          className={activeTab === 'search' ? 'hud-button active' : 'hud-button'}
          onClick={() => setActiveTab('search')}
        >
          SEARCH
        </button>
        <button
          className={activeTab === 'browse' ? 'hud-button active' : 'hud-button'}
          onClick={() => setActiveTab('browse')}
        >
          BROWSE
        </button>
        <button
          className={activeTab === 'deep' ? 'hud-button active' : 'hud-button'}
          onClick={() => setActiveTab('deep')}
        >
          DEEP SEARCH
        </button>
        <button
          className={activeTab === 'mentions' ? 'hud-button active' : 'hud-button'}
          onClick={() => setActiveTab('mentions')}
        >
          MENTIONS ({mentions.length})
        </button>
        <button
          className={activeTab === 'ransomware' ? 'hud-button active' : 'hud-button'}
          onClick={() => setActiveTab('ransomware')}
        >
          RANSOMWARE
        </button>
        <button
          className={activeTab === 'breach' ? 'hud-button active' : 'hud-button'}
          onClick={() => setActiveTab('breach')}
        >
          BREACH
        </button>
      </div>

      {activeTab === 'search' && (
        <>
          <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
            <input
              className="hud-input"
              style={{ flex: 1 }}
              placeholder="Search query (entity, keyword, .onion)"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            />
            <input
              className="hud-input"
              style={{ width: 160 }}
              placeholder="ahmia,darksearch"
              value={engines}
              onChange={(e) => setEngines(e.target.value)}
              title="Comma-separated engines"
            />
            <select
              className="hud-input"
              style={{ width: 100 }}
              value={mode}
              onChange={(e) => setMode(e.target.value as 'auto' | 'clear' | 'tor')}
              title="Routing mode: auto (clearnet engines direct, Tor engines via proxy), clear (clearnet only), tor (all via Tor proxy)"
            >
              <option value="auto">AUTO</option>
              <option value="clear">CLEAR</option>
              <option value="tor">TOR</option>
            </select>
            <button className="hud-button" onClick={handleSearch} disabled={loading}>
              {loading ? '...' : 'SEARCH'}
            </button>
            <button
              className="hud-button"
              onClick={() => handleIngest()}
              disabled={loading || !query}
            >
              INGEST
            </button>
          </div>

          {error && <div style={{ color: '#ff4d5e', marginBottom: 12 }}>{error}</div>}

          {matches.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <h3 style={{ fontSize: 13, color: '#ffd23f', marginBottom: 6 }}>
                MATCHED ENTITIES ({matches.length})
              </h3>
              {matches.map((m, idx) => (
                <div
                  key={idx}
                  style={{
                    padding: 8,
                    marginBottom: 6,
                    borderLeft: '2px solid #ffd23f',
                    background: '#ffffff08',
                  }}
                >
                  <div style={{ fontSize: 12, color: '#00e5a0' }}>{m.matched_names.join(', ')}</div>
                  <div style={{ fontSize: 11, color: '#b0c4bf' }}>{m.result.title}</div>
                  <div style={{ fontSize: 10, color: '#6f8c84', wordBreak: 'break-all' }}>
                    {m.result.url}
                  </div>
                </div>
              ))}
            </div>
          )}

          {results.length > 0 && (
            <div>
              <h3 style={{ fontSize: 13, color: '#00e5a0', marginBottom: 6 }}>
                RESULTS ({results.length})
              </h3>
              {results.map((r, idx) => (
                <div
                  key={idx}
                  style={{
                    padding: 8,
                    marginBottom: 6,
                    borderLeft: '2px solid #6f8c84',
                    background: '#ffffff08',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ fontSize: 12, color: '#e0f2f1' }}>{r.title}</span>
                    <span style={{ fontSize: 10, color: '#8fb7a9' }}>{r.engine}</span>
                  </div>
                  <div style={{ fontSize: 11, color: '#b0c4bf', marginTop: 4 }}>{r.snippet}</div>
                  <div
                    style={{ fontSize: 10, color: '#6f8c84', wordBreak: 'break-all', marginTop: 4 }}
                  >
                    {r.url}
                  </div>
                  <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
                    <button
                      className="hud-button"
                      style={{ fontSize: 10, padding: '2px 8px' }}
                      onClick={() => openInBrowse(r.url)}
                    >
                      BROWSE
                    </button>
                  </div>
                  {r.extracted_entities && Object.keys(r.extracted_entities).length > 0 && (
                    <div style={{ marginTop: 4, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                      {Object.entries(r.extracted_entities).map(([k, vals]) => (
                        <span
                          key={k}
                          style={{
                            fontSize: 10,
                            padding: '1px 4px',
                            borderRadius: 3,
                            background: '#00000033',
                            color: '#ffd23f',
                          }}
                        >
                          {k}: {vals.slice(0, 3).join(', ')}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {activeTab === 'browse' && (
        <>
          <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
            <input
              className="hud-input"
              style={{ flex: 1 }}
              placeholder="Enter .onion URL or any URL to scrape"
              value={browseUrl}
              onChange={(e) => setBrowseUrl(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleBrowse()}
            />
            <button className="hud-button" onClick={() => handleBrowse()} disabled={browseLoading}>
              {browseLoading ? '...' : 'SCRAPE'}
            </button>
          </div>

          {browseHistory.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 11, color: '#6f8c84', marginBottom: 4 }}>RECENT</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                {browseHistory.map((h, idx) => (
                  <button
                    key={idx}
                    className="hud-button"
                    style={{
                      fontSize: 10,
                      padding: '2px 6px',
                      maxWidth: 200,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                    title={h}
                    onClick={() => {
                      setBrowseUrl(h);
                      handleBrowse(h);
                    }}
                  >
                    {h}
                  </button>
                ))}
              </div>
            </div>
          )}

          {error && <div style={{ color: '#ff4d5e', marginBottom: 12 }}>{error}</div>}

          {browseResult && (
            <div>
              {browseResult.ok ? (
                <>
                  <div style={{ fontSize: 11, color: '#00e5a0', marginBottom: 6 }}>
                    Scraped: {browseResult.url} ({browseResult.text.length} chars)
                  </div>
                  {browseResult.entities && Object.keys(browseResult.entities).length > 0 && (
                    <div style={{ marginBottom: 8, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                      {Object.entries(browseResult.entities).map(([k, vals]) => (
                        <span
                          key={k}
                          style={{
                            fontSize: 10,
                            padding: '2px 6px',
                            borderRadius: 3,
                            background: '#ffd23f22',
                            color: '#ffd23f',
                          }}
                        >
                          {k}: {vals.slice(0, 3).join(', ')}
                        </span>
                      ))}
                    </div>
                  )}
                  <pre
                    style={{
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-word',
                      fontSize: 11,
                      color: '#b0c4bf',
                      background: '#00000044',
                      padding: 8,
                      borderRadius: 4,
                      maxHeight: '60vh',
                      overflow: 'auto',
                      margin: 0,
                    }}
                  >
                    {browseResult.text}
                  </pre>
                </>
              ) : (
                <div style={{ color: '#ff4d5e' }}>
                  Failed to scrape: {browseResult.error || 'Unknown error'}
                </div>
              )}
            </div>
          )}

          {!browseResult && !browseLoading && !error && (
            <div style={{ color: '#6f8c84' }}>
              Enter a URL above to scrape and view page content. Works with .onion URLs when Tor
              proxy is configured.
            </div>
          )}
        </>
      )}

      {activeTab === 'deep' && (
        <>
          <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
            <input
              className="hud-input"
              style={{ flex: 1, minWidth: 200 }}
              placeholder="Deep search query — searches + scrapes top results"
              value={deepQuery}
              onChange={(e) => setDeepQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleDeepSearch()}
            />
            <input
              className="hud-input"
              style={{ width: 160 }}
              placeholder="ahmia,darksearch"
              value={engines}
              onChange={(e) => setEngines(e.target.value)}
              title="Comma-separated engines"
            />
            <select
              className="hud-input"
              style={{ width: 100 }}
              value={mode}
              onChange={(e) => setMode(e.target.value as 'auto' | 'clear' | 'tor')}
            >
              <option value="auto">AUTO</option>
              <option value="clear">CLEAR</option>
              <option value="tor">TOR</option>
            </select>
            <input
              className="hud-input"
              style={{ width: 80 }}
              type="number"
              min={1}
              max={10}
              value={deepScrapeLimit}
              onChange={(e) => setDeepScrapeLimit(Number(e.target.value))}
              title="Number of results to scrape"
            />
            <button className="hud-button" onClick={handleDeepSearch} disabled={deepLoading}>
              {deepLoading ? '...' : 'DEEP SEARCH'}
            </button>
          </div>

          {error && <div style={{ color: '#ff4d5e', marginBottom: 12 }}>{error}</div>}

          {deepResults.length > 0 && (
            <div>
              <h3 style={{ fontSize: 13, color: '#00e5a0', marginBottom: 6 }}>
                DEEP RESULTS ({deepResults.length})
              </h3>
              {deepResults.map((d, idx) => (
                <div
                  key={idx}
                  style={{
                    padding: 8,
                    marginBottom: 8,
                    borderLeft: '2px solid #00e5a0',
                    background: '#ffffff08',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ fontSize: 12, color: '#e0f2f1' }}>{d.result.title}</span>
                    <span style={{ fontSize: 10, color: '#8fb7a9' }}>{d.result.engine}</span>
                  </div>
                  <div
                    style={{ fontSize: 10, color: '#6f8c84', wordBreak: 'break-all', marginTop: 2 }}
                  >
                    {d.result.url}
                  </div>
                  {d.matched_names.length > 0 && (
                    <div style={{ fontSize: 10, color: '#ffd23f', marginTop: 2 }}>
                      Entities: {d.matched_names.join(', ')}
                    </div>
                  )}
                  {d.scrape.ok && (
                    <>
                      {d.scrape.entities && Object.keys(d.scrape.entities).length > 0 && (
                        <div style={{ marginTop: 4, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                          {Object.entries(d.scrape.entities).map(([k, vals]) => (
                            <span
                              key={k}
                              style={{
                                fontSize: 10,
                                padding: '1px 4px',
                                borderRadius: 3,
                                background: '#ffd23f22',
                                color: '#ffd23f',
                              }}
                            >
                              {k}: {vals.slice(0, 3).join(', ')}
                            </span>
                          ))}
                        </div>
                      )}
                      <pre
                        style={{
                          whiteSpace: 'pre-wrap',
                          wordBreak: 'break-word',
                          fontSize: 10,
                          color: '#b0c4bf',
                          background: '#00000033',
                          padding: 6,
                          borderRadius: 3,
                          maxHeight: '200px',
                          overflow: 'auto',
                          margin: '4px 0 0 0',
                        }}
                      >
                        {d.scrape.text.slice(0, 2000)}
                        {d.scrape.text.length > 2000 ? '\n...[truncated]' : ''}
                      </pre>
                    </>
                  )}
                  {d.scrape.ok === false && (
                    <div style={{ fontSize: 10, color: '#ff4d5e', marginTop: 4 }}>
                      Scrape failed: {d.scrape.error}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {deepResults.length === 0 && !deepLoading && !error && (
            <div style={{ color: '#6f8c84' }}>
              Deep search runs a normal search, then scrapes the top results and extracts entities
              from each page.
            </div>
          )}
        </>
      )}

      {activeTab === 'mentions' && (
        <div>
          {mentions.length === 0 && (
            <div style={{ color: '#6f8c84' }}>No dark web mentions ingested yet.</div>
          )}
          {mentions.map((m, idx) => {
            const p = m.properties || {};
            return (
              <div
                key={idx}
                style={{
                  padding: 8,
                  marginBottom: 6,
                  borderLeft: '2px solid #00e5a0',
                  background: '#ffffff08',
                }}
              >
                <div style={{ fontSize: 12, color: '#e0f2f1' }}>{(p.name || ['Unknown'])[0]}</div>
                <div style={{ fontSize: 10, color: '#8fb7a9' }}>
                  source: {(p.source || ['darkweb'])[0]}
                </div>
                <div style={{ fontSize: 10, color: '#6f8c84', wordBreak: 'break-all' }}>
                  {(p.url || [''])[0]}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {activeTab === 'ransomware' && (
        <div>
          <div style={{ display: 'flex', gap: 8, marginBottom: 12, alignItems: 'center' }}>
            <select
              className="hud-input"
              style={{ flex: 1 }}
              value={selectedRansomwareGroup}
              onChange={(e) => setSelectedRansomwareGroup(e.target.value)}
            >
              <option value="">Select group...</option>
              {ransomwareGroups.map((g) => (
                <option key={g.name} value={g.name}>
                  {g.name} {g.url ? `· ${g.url}` : ''}
                </option>
              ))}
            </select>
            <button
              className="hud-button"
              onClick={handleRefreshRansomware}
              disabled={ransomwareLoading}
            >
              REFRESH
            </button>
            <button
              className="hud-button"
              onClick={handleIngestRansomware}
              disabled={ransomwareLoading || !selectedRansomwareGroup}
            >
              INGEST
            </button>
          </div>
          {ransomwareLoading && <div style={{ color: '#8fb7a9' }}>Loading...</div>}
          {ransomwareVictims.length === 0 && !ransomwareLoading && (
            <div style={{ color: '#6f8c84' }}>Select a group and fetch victims.</div>
          )}
          {ransomwareVictims.map((v, idx) => (
            <div
              key={idx}
              style={{
                padding: 8,
                marginBottom: 6,
                borderLeft: '2px solid #ff4d5e',
                background: '#ffffff08',
              }}
            >
              <div style={{ fontSize: 12, color: '#e0f2f1' }}>{v.victim}</div>
              <div style={{ fontSize: 10, color: '#8fb7a9' }}>
                group: {v.group} {v.discovered && `· ${v.discovered}`}{' '}
                {v.country && `· ${v.country}`}
              </div>
              {v.description && (
                <div style={{ fontSize: 10, color: '#6f8c84', marginTop: 4 }}>{v.description}</div>
              )}
            </div>
          ))}
        </div>
      )}

      {activeTab === 'breach' && (
        <div>
          <div style={{ marginBottom: 16 }}>
            <h3 style={{ fontSize: 13, color: '#00e5a0', margin: '0 0 8px 0' }}>
              EMAIL BREACH CHECK (HIBP)
            </h3>
            <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
              <input
                className="hud-input"
                style={{ flex: 1 }}
                placeholder="email@example.com"
                value={breachEmail}
                onChange={(e) => setBreachEmail(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleBreachCheck()}
              />
              <button
                className="hud-button"
                onClick={handleBreachCheck}
                disabled={breachLoading || !breachEmail.trim()}
              >
                {breachLoading ? '...' : 'CHECK'}
              </button>
            </div>
            {breachResult && (
              <div style={{ fontSize: 11, marginTop: 8 }}>
                {breachResult.error ? (
                  <div style={{ color: '#ff4d5e' }}>Error: {breachResult.error}</div>
                ) : breachResult.breached ? (
                  <div>
                    <div style={{ color: '#ff4d5e', marginBottom: 4 }}>
                      {breachResult.email} — {breachResult.count} breach(es) found
                    </div>
                    {breachResult.breaches.map((b) => (
                      <div
                        key={b.name}
                        style={{
                          background: '#00000033',
                          padding: 6,
                          borderRadius: 3,
                          marginBottom: 4,
                        }}
                      >
                        <div style={{ color: '#ff8a65', fontSize: 11 }}>
                          {b.title} ({b.breach_date})
                        </div>
                        <div style={{ fontSize: 10, color: '#b0c4bf' }}>
                          {b.pwn_count.toLocaleString()} accounts · Classes:{' '}
                          {b.data_classes.join(', ')}
                        </div>
                        {b.is_sensitive && (
                          <span style={{ fontSize: 10, color: '#ffd23f' }}> SENSITIVE</span>
                        )}
                        {!b.is_verified && (
                          <span style={{ fontSize: 10, color: '#ffd23f' }}> UNVERIFIED</span>
                        )}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div style={{ color: '#00e5a0' }}>{breachResult.email} — No breaches found</div>
                )}
              </div>
            )}
          </div>

          <div style={{ marginBottom: 16 }}>
            <h3 style={{ fontSize: 13, color: '#00e5a0', margin: '0 0 8px 0' }}>
              PASSWORD CHECK (k-anonymity)
            </h3>
            <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
              <input
                className="hud-input"
                type="password"
                style={{ flex: 1 }}
                placeholder="Password to check (SHA1 sent via k-anonymity)"
                value={breachPassword}
                onChange={(e) => setBreachPassword(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handlePasswordCheck()}
              />
              <button
                className="hud-button"
                onClick={handlePasswordCheck}
                disabled={breachLoading || !breachPassword.trim()}
              >
                {breachLoading ? '...' : 'CHECK'}
              </button>
            </div>
            {breachPasswordResult && (
              <div style={{ fontSize: 11, marginTop: 4 }}>
                {breachPasswordResult.error ? (
                  <div style={{ color: '#ff4d5e' }}>Error: {breachPasswordResult.error}</div>
                ) : breachPasswordResult.compromised ? (
                  <div style={{ color: '#ff4d5e' }}>
                    COMPROMISED — found {breachPasswordResult.count.toLocaleString()} time(s) in
                    breach dumps
                  </div>
                ) : (
                  <div style={{ color: '#00e5a0' }}>Not found in any known breach</div>
                )}
              </div>
            )}
          </div>

          <div style={{ marginBottom: 16 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
              <h3 style={{ fontSize: 13, color: '#00e5a0', margin: 0 }}>
                MONITORED EMAILS ({breachMonitors.length})
              </h3>
              <button
                className="hud-button"
                onClick={handleBreachRefresh}
                disabled={breachLoading || breachMonitors.length === 0}
                style={{ fontSize: 10 }}
              >
                {breachLoading ? '...' : 'REFRESH ALL'}
              </button>
            </div>
            {breachRefreshResult && (
              <div style={{ fontSize: 11, color: '#b0c4bf', marginBottom: 8 }}>
                Checked: {breachRefreshResult.checked} · New breaches:{' '}
                {breachRefreshResult.new_breaches}
              </div>
            )}
            {breachMonitors.length === 0 ? (
              <div style={{ fontSize: 11, color: '#6f8c84' }}>
                No monitored emails. Check an email above with monitor=true to add it.
              </div>
            ) : (
              breachMonitors.map((m) => (
                <div
                  key={m.id}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    background: '#00000033',
                    padding: 6,
                    borderRadius: 3,
                    marginBottom: 4,
                  }}
                >
                  <div>
                    <span style={{ fontSize: 11, color: '#00e5a0' }}>{m.email_label}</span>
                    <span style={{ fontSize: 10, color: '#6f8c84', marginLeft: 8 }}>
                      {m.last_breach_count} breach(es)
                    </span>
                    {m.last_checked && (
                      <span style={{ fontSize: 10, color: '#6f8c84', marginLeft: 8 }}>
                        checked: {new Date(m.last_checked).toLocaleDateString()}
                      </span>
                    )}
                  </div>
                  <button
                    className="hud-button"
                    onClick={() => handleRemoveMonitor(m.id)}
                    style={{ fontSize: 10, padding: '2px 6px' }}
                  >
                    REMOVE
                  </button>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
