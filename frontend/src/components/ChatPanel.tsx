import { useState, useEffect, useRef } from 'react';
import { fetchApi } from '../lib/networkFetch';

import FirewallMonitor from './FirewallMonitor';

const CHAT_SESSION_KEY = 'worldbase_chat_session_id'

function getChatSessionId(): string {
  try {
    let id = sessionStorage.getItem(CHAT_SESSION_KEY)
    if (!id) {
      id = typeof crypto !== 'undefined' && crypto.randomUUID
        ? crypto.randomUUID()
        : `wb-${Date.now()}-${Math.random().toString(36).slice(2, 11)}`
      sessionStorage.setItem(CHAT_SESSION_KEY, id)
    }
    return id
  } catch {
    return `wb-${Date.now()}`
  }
}

export default function ChatPanel({
  askAI,
  onClearAsk,
  onFirewallResult,
  onClientAction,
}: {
  askAI?: { id: number; question: string; context: string } | null
  onClearAsk?: () => void
  onFirewallResult?: (r: any) => void
  onClientAction?: (act: any) => void
}) {
  const [msg, setMsg] = useState('')
  const [history, setHistory] = useState<{ role: string; content: string }[]>([
    { role: 'system', content: 'Select a model and start chatting.' },
  ])
  const [providers, setProviders] = useState<{ id: string; name: string; models: string[]; requires_key: boolean }[]>([])
  const [provider, setProvider] = useState('ollama')
  const [models, setModels] = useState<{ name: string; parameter_size?: string }[]>([])
  const [model, setModel] = useState('')
  const [busy, setBusy] = useState(false)
  const [genStatus, setGenStatus] = useState<string | null>(null)
  const [modelErr, setModelErr] = useState<string | null>(null)
  const [modelsLoading, setModelsLoading] = useState(true)
  const [modelHint, setModelHint] = useState<string | null>(null)
  const [webSearch, setWebSearch] = useState(false)
  const [feedContext, setFeedContext] = useState(false)
  const [useTools, setUseTools] = useState(false)
  const [firewall, setFirewall] = useState(false)
  const [firewallMeta, setFirewallMeta] = useState<any>(null)
  const [genWaitSec, setGenWaitSec] = useState(0)
  const processedAskIdRef = useRef(0)

  const loadModels = () => {
    setModelErr(null)
    setModelHint(null)
    setModelsLoading(true)
    fetchApi('/api/models')
      .then((r) => r.json())
      .then((d) => {
        if (d.error) {
          const extra = [d.hint, d.detail, d.hosts_tried?.length ? `hosts: ${d.hosts_tried.join(', ')}` : '']
            .filter(Boolean)
            .join(' · ')
          setModelErr(d.error)
          setModelHint(extra || 'Check: Is Ollama running? Backend on :8002? Frontend via .\\start.ps1 (:5176)?')
          return
        }
        if (d.warning) setModelHint(d.warning)
        const list = (d.models || []).filter((m: { name: string }) => !/embed/i.test(m.name))
        setModels(list)
        if (list.length > 0) {
          const preferred = d.default as string | undefined
          const pick = preferred && list.some((m: { name: string }) => m.name === preferred)
            ? preferred
            : list[0].name
          setModel(pick)
        } else {
          setModelErr('No chat model in Ollama')
          setModelHint('ollama pull qwen3:8b')
        }
      })
      .catch(() => {
        setModelErr('Backend unreachable')
        setModelHint('Start with .\\start.ps1 — Frontend :5176, Backend :8002')
      })
      .finally(() => setModelsLoading(false))

    fetchApi('/api/providers')
      .then((r) => r.json())
      .then((d) => {
        const list = d.providers || []
        setProviders(list.length ? list : [{ id: 'ollama', name: 'Ollama (Local)', models: [], requires_key: false }])
      })
      .catch(() => {
        setProviders([{ id: 'ollama', name: 'Ollama (Local)', models: [], requires_key: false }])
      })
  }

  useEffect(() => {
    loadModels()
  }, [])

  useEffect(() => {
    if (!busy) {
      setGenWaitSec(0)
      return
    }
    const t0 = Date.now()
    setGenWaitSec(0)
    const id = setInterval(() => {
      setGenWaitSec(Math.floor((Date.now() - t0) / 1000))
    }, 1000)
    return () => clearInterval(id)
  }, [busy])

  // Auto-send when askAI is provided (from globe / situation board)
  useEffect(() => {
    if (!askAI || busy) return
    if (askAI.id <= processedAskIdRef.current) return
    const activeModel = model || models[0]?.name
    if (!activeModel) return

    const pending = askAI
    setMsg(`${pending.question}\n\n${pending.context}`)
    const t = setTimeout(() => {
      processedAskIdRef.current = pending.id
      void sendWithMessage(pending.question, pending.context, { forceFast: true })
      onClearAsk?.()
    }, 100)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [askAI, busy, model, models])

  async function sendWithMessage(
    userMsg: string,
    entityCtx?: string,
    opts?: { forceFast?: boolean },
  ) {
    const text = userMsg.trim()
    if (busy || !text) return
    let activeModel = model
    if (!activeModel && models.length > 0) {
      activeModel = models[0].name
      setModel(activeModel)
    }
    if (!activeModel) return

    const isEntityAsk = Boolean(entityCtx)
    const forceFast = opts?.forceFast ?? isEntityAsk
    const useCtx = !forceFast && feedContext
    const useWebSearch = !forceFast && webSearch
    const useToolCalls = !forceFast && useTools && provider === 'ollama'

    setMsg('')
    setFirewallMeta(null)
    const userDisplay = entityCtx ? `${text}\n\n${entityCtx}` : text
    setHistory((h) => [...h, { role: 'user', content: userDisplay }])
    setHistory((h) => [...h, { role: 'assistant', content: '' }])
    setBusy(true)
    setGenStatus(forceFast ? 'Entity analysis (fast)…' : 'Starting…')

    let searchCtx = ''
    if (useWebSearch) {
      const searchQ = isEntityAsk && entityCtx
        ? entityCtx.split('\n')[0].replace(/^Entity:\s*/, '').trim() || text
        : text
      setGenStatus('🔍 DuckDuckGo search…')
      try {
        const sr = await fetchApi(`/api/search?q=${encodeURIComponent(searchQ)}&n=5`)
        const sd = await sr.json()
        if (sd.results && sd.results.length > 0) {
          searchCtx = sd.results.map((r: any, i: number) =>
            `[${i + 1}] ${r.title}\n${r.snippet}\nURL: ${r.url}`
          ).join('\n\n')
        }
      } catch {
        // search failed silently, continue without context
      }
    }

    if (useCtx) setGenStatus('Loading situation picture (CTX)…')
    else if (useToolCalls) setGenStatus('Ollama + tools — may take 30–90s…')
    else if (forceFast) setGenStatus('Ollama analyzing target…')
    else setGenStatus('Contacting Ollama…')

    try {
      const r = await fetchApi('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'text/event-stream' },
        body: JSON.stringify({
          model: activeModel,
          messages: [{ role: 'user', content: text }],
          stream: true,
          context: useCtx,
          provider,
          entity_context: entityCtx || undefined,
          search_results: searchCtx || undefined,
          firewall,
          chat_session_id: getChatSessionId(),
          use_tools: useToolCalls,
          force_fast: forceFast,
        }),
      })
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
      if (!r.body) throw new Error('No response body')

      const reader = r.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        // Parse SSE lines: data: {...}
        const lines = buffer.split('\n\n')
        buffer = lines.pop() || ''  // keep incomplete chunk

        for (const chunk of lines) {
          const m = chunk.match(/^data: (.+)$/m)
          if (!m) continue
          try {
            const data = JSON.parse(m[1])
            if (data.error) {
              setHistory((h) => {
                const copy = [...h]
                copy[copy.length - 1] = { role: 'assistant', content: 'Error: ' + data.error }
                return copy
              })
              break
            }
            if (data.firewall_result) {
              console.log('[FIREWALL] result:', data.firewall_result)
              setFirewallMeta(data.firewall_result)
              onFirewallResult?.({
                timestamp: Date.now(),
                query: text,
                ...data.firewall_result,
              })
              continue
            }
            if (data.firewall_blocked) {
              console.log('[FIREWALL] blocked meta:', data.firewall_meta)
              if (data.firewall_meta) {
                setFirewallMeta(data.firewall_meta)
                onFirewallResult?.({
                  timestamp: Date.now(),
                  query: text,
                  ...data.firewall_meta,
                })
              }
              setHistory((h) => {
                const copy = [...h]
                copy[copy.length - 1] = { role: 'assistant', content: data.message?.content || 'Blocked by firewall.' }
                return copy
              })
              break
            }
            if (data.status) {
              const labels: Record<string, string> = {
                preparing: 'Loading situation & context…',
                tools: 'Ollama analyzing (tools active)…',
                generating: 'Ollama generating response…',
              }
              if (data.status === 'tool' && data.tool) {
                setGenStatus(`Tool: ${data.tool}…`)
              } else {
                setGenStatus(labels[data.status as string] || String(data.status))
              }
            }
            if (data.done) {
              setGenStatus(null)
              break
            }
            if (data.client_action) {
              onClientAction?.(data.client_action)
            }
            if (data.token) {
              setGenStatus('Ollama generating response…')
              setHistory((h) => {
                const copy = [...h]
                copy[copy.length - 1] = {
                  role: 'assistant',
                  content: copy[copy.length - 1].content + data.token,
                }
                return copy
              })
            }
          } catch {
            // ignore malformed SSE
          }
        }
      }
    } catch (e) {
      setHistory((h) => {
        const copy = [...h]
        copy[copy.length - 1] = { role: 'assistant', content: 'Error: ' + (e as Error).message }
        return copy
      })
    } finally {
      setBusy(false)
      setGenStatus(null)
    }
  }

  const isOllama = provider === 'ollama'
  const providerModels = providers.find((p) => p.id === provider)?.models || []

  return (
    <div className="panel chat">
      <h2>WorldBase AI <span style={{ color: '#ff2d00', fontSize: 10 }}>[FIREWALL UI v1.0]</span></h2>

      {modelErr && (
        <div className="data-error">
          {modelErr}
          {modelHint && <div style={{ marginTop: 6, fontSize: 11, opacity: 0.9 }}>{modelHint}</div>}
          <button type="button" className="web-search" style={{ marginTop: 8, fontSize: 10 }} onClick={loadModels}>
            ↻ RETRY
          </button>
        </div>
      )}
      {!modelErr && modelHint && (
        <div className="data-error" style={{ borderColor: '#ffd23f', color: '#ffd23f' }}>{modelHint}</div>
      )}
      {(feedContext || webSearch || useTools) && !busy && (
        <div className="chat-slow-hint">
          CTX / 🔍 / TOOLS active — manual chats often take 30–90&nbsp;s. Ask AI from the globe uses the fast entity path automatically.
        </div>
      )}

      <div className="model-select">
        <select
          value={provider}
          onChange={(e) => {
            const pid = e.target.value
            setProvider(pid)
            const p = providers.find((x) => x.id === pid)
            if (p && p.models.length > 0) {
              setModel(p.models[0])
            } else if (pid === 'ollama' && models.length > 0) {
              setModel(models[0].name)
            }
          }}
          style={{ marginRight: 6 }}
        >
          {providers.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>

        {isOllama ? (
          <select value={model} onChange={(e) => setModel(e.target.value)} disabled={models.length === 0}>
            {models.length === 0 && modelsLoading && <option value="">Loading models…</option>}
            {models.length === 0 && !modelsLoading && <option value="">No models found</option>}
            {models.map((m) => (
              <option key={m.name} value={m.name}>
                {m.name} {m.parameter_size ? `(${m.parameter_size})` : ''}
              </option>
            ))}
          </select>
        ) : (
          <>
            <input
              list={`models-${provider}`}
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="model name"
              style={{ width: 180, fontSize: 12 }}
            />
            <datalist id={`models-${provider}`}>
              {providerModels.map((m) => (
                <option key={m} value={m} />
              ))}
            </datalist>
          </>
        )}

        <button
          className={useTools ? 'web-search on' : 'web-search'}
          onClick={() => setUseTools((v) => !v)}
          title="Ollama tool rounds (situations, OSINT) — slower but smarter"
        >
          {useTools ? 'TOOLS ON' : 'TOOLS OFF'}
        </button>
        <button
          className={feedContext ? 'web-search on' : 'web-search'}
          onClick={() => setFeedContext((v) => !v)}
          title="WorldBase situation picture: nodes, feeds, headlines, CVE in prompt"
        >
          {feedContext ? 'CTX ON' : 'CTX OFF'}
        </button>
        <button
          className={webSearch ? 'web-search on' : 'web-search'}
          onClick={() => setWebSearch((v) => !v)}
          title="Toggle web search (injects DuckDuckGo results as context)"
        >
          {webSearch ? '🔍 ON' : '🔍 OFF'}
        </button>
        <button
          className={firewall ? 'web-search on' : 'web-search'}
          onClick={() => setFirewall((v) => !v)}
          title="Toggle LLM-Security-Firewall (scans prompts via external HAK_GAL service)"
          style={{ marginLeft: 6, color: firewall ? '#ff2d00' : '#6f8c84' }}
        >
          {firewall ? '🛡️ ON' : '🛡️ OFF'}
        </button>
      </div>

      {firewall && (
        <div style={{ background: '#ff2d00', color: '#fff', padding: '6px 10px', fontSize: 11, borderRadius: 4, marginBottom: 8, fontFamily: 'monospace', fontWeight: 'bold' }}>
          🛡️ FIREWALL ACTIVE | Status: {busy ? 'SCANNING...' : (firewallMeta ? 'RESULT RECEIVED' : 'IDLE')}
        </div>
      )}

      {firewall && (
        <div style={{ border: '1px solid #333', borderRadius: 6, padding: 10, marginBottom: 8, background: '#0a0f0d', minHeight: 60 }}>
          {firewallMeta ? (
            <FirewallMonitor meta={firewallMeta} />
          ) : (
            <div style={{ color: '#6f8c84', fontSize: 11, textAlign: 'center', padding: '20px 0' }}>
              {busy ? '⏳ Scanning through HAK_GAL firewall...' : 'Send a message to see firewall analysis'}
            </div>
          )}
        </div>
      )}

      {busy && genStatus && (
        <div className="chat-gen-status" role="status" aria-live="polite">
          <span className="chat-gen-pulse" />
          <span>{genStatus}{genWaitSec > 0 ? ` (${genWaitSec}s)` : ''}</span>
        </div>
      )}

      <div className="chat-history">
        {history.map((m, i) => (
          <div key={i} className={`chat-msg ${m.role}`}>
            <strong>{m.role}:</strong>{' '}
            {m.role === 'assistant' && !m.content && busy && i === history.length - 1 ? (
              <span className="chat-waiting">{genStatus || '…'}</span>
            ) : (
              m.content
            )}
            {m.role === 'assistant' && busy && i === history.length - 1 && (
              <span className="chat-cursor" aria-hidden="true">▌</span>
            )}
          </div>
        ))}
      </div>
      <div className="chat-input">
        <input
          value={msg}
          onChange={(e) => setMsg(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && !busy && msg.trim() && sendWithMessage(msg.trim())}
          placeholder={model ? `Ask ${model} (${provider})…` : 'Select a model first…'}
          disabled={!model}
        />
        <button onClick={() => sendWithMessage(msg.trim())} disabled={busy || !model}>
          Send
        </button>
      </div>
    </div>
  )
}

