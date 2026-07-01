import { useCallback, useEffect, useState } from 'react';
import { fetchApi } from '../lib/networkFetch';

type StoredCredential = {
  env_var: string;
  masked: string;
  has_value: boolean;
};

type ProviderStatus = {
  id: string;
  name: string;
  category: string;
  tier: string;
  configured: boolean;
  env_vars: string[];
  missing_env: string[];
  feeds: string[];
  docs_url: string;
  license_note: string;
  notes: string | null;
};

type ProvidersResponse = {
  count: number;
  configured: number;
  optional_total: number;
  providers: (ProviderStatus | null)[];
};

type CredentialsResponse = {
  credentials: StoredCredential[];
};

export default function CredentialManagerPanel() {
  const [providers, setProviders] = useState<ProvidersResponse | null>(null);
  const [stored, setStored] = useState<StoredCredential[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [envVar, setEnvVar] = useState('');
  const [value, setValue] = useState('');
  const [showValue, setShowValue] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [pRes, cRes] = await Promise.all([
        fetchApi('/api/credentials/status'),
        fetchApi('/api/credentials'),
      ]);
      if (pRes.ok) setProviders(await pRes.json());
      if (cRes.ok) {
        const c: CredentialsResponse = await cRes.json();
        setStored(c.credentials);
      }
    } catch (e: unknown) {
      setError(`load: ${(e as Error).message || e}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const submit = async () => {
    if (!envVar.trim() || !value.trim()) {
      setError('Both env var and value are required');
      return;
    }
    setError(null);
    setInfo(null);
    try {
      const r = await fetchApi('/api/credentials', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ env_var: envVar.trim(), value: value.trim() }),
      });
      const d = await r.json();
      if (d.error) {
        setError(d.error);
        return;
      }
      setInfo(`✓ Set ${envVar.trim().toUpperCase()}`);
      setEnvVar('');
      setValue('');
      load();
    } catch (e: unknown) {
      setError(`set: ${(e as Error).message || e}`);
    }
  };

  const remove = async (varName: string) => {
    setError(null);
    setInfo(null);
    try {
      const r = await fetchApi(`/api/credentials/${encodeURIComponent(varName)}`, {
        method: 'DELETE',
      });
      const d = await r.json();
      if (d.error) {
        setError(d.error);
        return;
      }
      setInfo(`✓ Removed ${varName}`);
      load();
    } catch (e: unknown) {
      setError(`delete: ${(e as Error).message || e}`);
    }
  };

  const apiKey = localStorage.getItem('WORLDBASE_API_KEY') || '';

  return (
    <div className="intel-panel">
      <div className="intel-section">
        <h3>
          🔑 Credential Manager{' '}
          <span className="stat-meta">
            {providers
              ? `${providers.configured}/${providers.count} providers configured`
              : 'Loading…'}
          </span>
        </h3>
        {loading && <div className="stat-meta">Loading…</div>}
        {error && <div className="data-error">{error}</div>}
        {info && (
          <div className="stat-meta" style={{ color: '#5bdc8f' }}>
            {info}
          </div>
        )}
      </div>

      {/* Add credential form */}
      <div className="intel-section">
        <h4>Add / Update Credential</h4>
        <div className="intel-toolbar">
          <input
            className="intel-dataset"
            placeholder="ENV_VAR_NAME"
            value={envVar}
            onChange={(e) => setEnvVar(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && submit}
          />
          <input
            className="intel-dataset wide"
            type={showValue ? 'text' : 'password'}
            placeholder="API key value"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && submit}
          />
          <button
            className="data-refresh"
            onClick={() => setShowValue(!showValue)}
            title="Toggle visibility"
          >
            {showValue ? '🙈' : '👁'}
          </button>
          <button className="data-refresh" onClick={submit}>
            SAVE
          </button>
        </div>
        {!apiKey && (
          <div className="stat-meta" style={{ color: '#ffd23f', marginTop: '4px' }}>
            ⚠ No WORLDBASE_API_KEY set — POST/DELETE require authentication. Set X-API-Key in
            localStorage.
          </div>
        )}
      </div>

      {/* Stored credentials */}
      {stored.length > 0 && (
        <div className="intel-section">
          <h4>Stored Credentials ({stored.length})</h4>
          <table className="data-table">
            <thead>
              <tr>
                <th>Env Var</th>
                <th>Value</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {stored.map((c) => (
                <tr key={c.env_var}>
                  <td>{c.env_var}</td>
                  <td>{c.masked}</td>
                  <td>
                    <button
                      className="data-refresh"
                      onClick={() => remove(c.env_var)}
                      style={{ color: '#ff7b6b' }}
                    >
                      DELETE
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Provider catalog */}
      {providers && (
        <div className="intel-section">
          <h4>Provider Catalog</h4>
          <table className="data-table">
            <thead>
              <tr>
                <th>Provider</th>
                <th>Category</th>
                <th>Tier</th>
                <th>Configured</th>
                <th>Env Vars</th>
                <th>Missing</th>
              </tr>
            </thead>
            <tbody>
              {providers.providers.filter(Boolean).map((p) => (
                <tr key={p!.id}>
                  <td>{p!.name}</td>
                  <td>{p!.category}</td>
                  <td>{p!.tier}</td>
                  <td style={{ color: p!.configured ? '#5bdc8f' : '#ff7b6b' }}>
                    {p!.configured ? '✓' : '✗'}
                  </td>
                  <td>{p!.env_vars.join(', ') || '—'}</td>
                  <td style={{ color: p!.missing_env.length ? '#ffd23f' : '' }}>
                    {p!.missing_env.join(', ') || '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
