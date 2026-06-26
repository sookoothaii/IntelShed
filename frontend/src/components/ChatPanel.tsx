import { useState, useEffect, useRef, useCallback } from 'react';
import { fetchApi } from '../lib/networkFetch';

import FirewallMonitor from './FirewallMonitor';

const CHAT_SESSION_KEY = 'worldbase_chat_session_id'
const CUSTOM_MODELS_KEY = 'worldbase_custom_models'
const SELECTED_MODELS_KEY = 'worldbase_selected_models'
const SELECTED_PROVIDER_KEY = 'worldbase_selected_provider'

function loadJsonRecord(key: string): Record<string, string> {
  try {
    return JSON.parse(localStorage.getItem(key) || '{}') || {}
  } catch {
    return {}
  }
}

function loadCustomModels(): Record<string, string[]> {
  try {
    const raw = JSON.parse(localStorage.getItem(CUSTOM_MODELS_KEY) || '{}') || {}
    const out: Record<string, string[]> = {}
    for (const [pid, list] of Object.entries(raw)) {
      if (Array.isArray(list)) {
        out[pid] = list.filter((m): m is string => typeof m === 'string' && m.trim().length > 0)
      }
    }
    return out
  } catch {
    return {}
  }
}

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
  onFirewallResult?: (r: unknown) => void
  onClientAction?: (act: unknown) => void
}) {
  const [msg, setMsg] = useState('')
  const [history, setHistory] = useState<{ role: string; content: string }[]>([
    { role: 'system', content: 'Select a model and start chatting.' },
  ])
  const [providers, setProviders] = useState<{ id: string; name: string; models: string[]; requires_key: boolean; key_set?: boolean; base_url_set?: boolean; default_base_url?: string | null; supports_tools?: boolean }[]>([])
  const [provider, setProvider] = useState(() => {
    try {
      return localStorage.getItem(SELECTED_PROVIDER_KEY) || 'ollama'
    } catch {
      return 'ollama'
    }
  })
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
  const [firewallMeta, setFirewallMeta] = useState<{ action: string; risk_score: number; flags?: string[]; policy_violations?: string[] } | null>(null)
  const [genWaitSec, setGenWaitSec] = useState(0)
  const [showSettings, setShowSettings] = useState(false)
  const [apiKeys, setApiKeys] = useState<Record<string, string>>(() => {
    try {
      return JSON.parse(localStorage.getItem('worldbase_api_keys') || '{}') || {}
    } catch {
      return {}
    }
  })
  const [apiBaseUrls, setApiBaseUrls] = useState<Record<string, string>>(() => {
    try {
      return JSON.parse(localStorage.getItem('worldbase_api_base_urls') || '{}') || {}
    } catch {
      return {}
    }
  })
  const [customModels, setCustomModels] = useState<Record<string, string[]>>(() => loadCustomModels())
  const [selectedModels, setSelectedModels] = useState<Record<string, string>>(() => loadJsonRecord(SELECTED_MODELS_KEY))
  const [showAddModel, setShowAddModel] = useState(false)
  const [newModelDraft, setNewModelDraft] = useState('')
  const [customModelDrafts, setCustomModelDrafts] = useState<Record<string, string>>({})
  const [rerankerWarming, setRerankerWarming] = useState(false)
  const processedAskIdRef = useRef(0)
  const abortRef = useRef<AbortController | null>(null)

  const stopGeneration = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    setBusy(false)
    setGenStatus(null)
    setHistory((h) => {
      const copy = [...h]
      if (copy.length > 0 && copy[copy.length - 1].role === 'assistant' && !copy[copy.length - 1].content) {
        copy[copy.length - 1] = { role: 'assistant', content: '⏹ Stopped by operator.' }
      }
      return copy
    })
  }, [])

  const saveApiKeys = (next: Record<string, string>) => {
    setApiKeys(next)
    try {
      localStorage.setItem('worldbase_api_keys', JSON.stringify(next))
    } catch {
      // ignore storage quota / privacy mode
    }
  }

  const saveApiBaseUrls = (next: Record<string, string>) => {
    setApiBaseUrls(next)
    try {
      localStorage.setItem('worldbase_api_base_urls', JSON.stringify(next))
    } catch {
      // ignore storage quota / privacy mode
    }
  }

  const saveCustomModels = (next: Record<string, string[]>) => {
    setCustomModels(next)
    try {
      localStorage.setItem(CUSTOM_MODELS_KEY, JSON.stringify(next))
    } catch {
      // ignore storage quota / privacy mode
    }
  }

  const rememberSelectedModel = (pid: string, modelName: string) => {
    if (!modelName.trim()) return
    const next = { ...selectedModels, [pid]: modelName.trim() }
    setSelectedModels(next)
    try {
      localStorage.setItem(SELECTED_MODELS_KEY, JSON.stringify(next))
    } catch {
      // ignore storage quota / privacy mode
    }
  }

  const mergedModelsForProvider = (pid: string, suggested: string[] = []) => {
    const custom = customModels[pid] || []
    const seen = new Set<string>()
    const out: string[] = []
    for (const name of [...suggested, ...custom]) {
      const trimmed = name.trim()
      if (!trimmed || seen.has(trimmed)) continue
      seen.add(trimmed)
      out.push(trimmed)
    }
    return out
  }

  const pickModelForProvider = (pid: string, suggested: string[] = []) => {
    const merged = mergedModelsForProvider(pid, suggested)
    if (merged.length === 0) return ''
    const remembered = selectedModels[pid]
    if (remembered && merged.includes(remembered)) return remembered
    return merged[0]
  }

  const addCustomModel = (pid: string, rawName: string) => {
    const name = rawName.trim()
    if (!name) return false
    const suggested = providers.find((p) => p.id === pid)?.models || []
    const merged = mergedModelsForProvider(pid, suggested)
    if (merged.includes(name)) {
      setModel(name)
      rememberSelectedModel(pid, name)
      if (provider !== pid) setProvider(pid)
      return true
    }
    const next = { ...customModels, [pid]: [...(customModels[pid] || []), name] }
    saveCustomModels(next)
    setModel(name)
    rememberSelectedModel(pid, name)
    if (provider !== pid) setProvider(pid)
    return true
  }

  const addCustomModelsFromDraft = (pid: string, raw: string) => {
    const names = raw.split(/[,;\n]+/).map((s) => s.trim()).filter(Boolean)
    if (names.length === 0) return false
    names.forEach((name) => addCustomModel(pid, name))
    setCustomModelDrafts((prev) => ({ ...prev, [pid]: '' }))
    return true
  }

  const customModelPlaceholder = (pid: string) => {
    if (pid === 'openrouter') return 'anthropic/claude-sonnet-4, google/gemini-2.5-pro-preview'
    if (pid === 'openai') return 'gpt-4o or custom deployment name'
    if (pid === 'nvidia') return 'qwen/qwen3.5-122b-a10b, deepseek-ai/deepseek-v4-flash'
    return 'model slug (comma-separated ok)'
  }

  const removeCustomModel = (pid: string, name: string) => {
    const nextList = (customModels[pid] || []).filter((m) => m !== name)
    const next = { ...customModels }
    if (nextList.length > 0) next[pid] = nextList
    else delete next[pid]
    saveCustomModels(next)
    if (model === name) {
      const suggested = providers.find((p) => p.id === pid)?.models || []
      setModel(pickModelForProvider(pid, suggested))
    }
  }

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
        const storedProvider = (() => {
          try {
            return localStorage.getItem(SELECTED_PROVIDER_KEY)
          } catch {
            return null
          }
        })()
        const defaultProvider = d.default_provider || 'ollama'
        const nextProvider = storedProvider || defaultProvider
        if (list.some((p: { id: string }) => p.id === nextProvider)) {
          setProvider(nextProvider)
        }
        if (d.default_model && !model) {
          const p = list.find((x: { id: string }) => x.id === nextProvider)
          const merged = [...(p?.models || []), ...(customModels[nextProvider] || [])]
          if (merged.includes(d.default_model)) {
            setModel(d.default_model)
          }
        }
      })
      .catch(() => {
        setProviders([{ id: 'ollama', name: 'Ollama (Local)', models: [], requires_key: false }])
      })
  }

  useEffect(() => {
    loadModels()
  }, [])

  useEffect(() => {
    if (provider === 'ollama' || providers.length === 0) return
    const p = providers.find((x) => x.id === provider)
    const merged = mergedModelsForProvider(provider, p?.models || [])
    if (merged.length === 0) {
      if (model) setModel('')
      return
    }
    if (!model || !merged.includes(model)) {
      setModel(pickModelForProvider(provider, p?.models || []))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [providers, customModels, provider])

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

  // I7: Poll reranker warmup status during startup
  useEffect(() => {
    let active = true
    const poll = async () => {
      try {
        const r = await fetchApi('/api/memory/reranker/status')
        if (!r.ok) return
        const d = await r.json()
        if (!active) return
        if (d.enabled && d.state === 'warming') {
          setRerankerWarming(true)
        } else if (d.state === 'ready' || d.state === 'failed' || !d.enabled) {
          setRerankerWarming(false)
        }
      } catch { /* best-effort */ }
    }
    poll()
    const id = setInterval(poll, 3000)
    const stop = setTimeout(() => { clearInterval(id); setRerankerWarming(false) }, 120000)
    return () => { active = false; clearInterval(id); clearTimeout(stop) }
  }, [])

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
    const useCtx = feedContext
    const useWebSearch = webSearch
    const useToolCalls = useTools

    setMsg('')
    setFirewallMeta(null)
    const userDisplay = entityCtx ? `${text}\n\n${entityCtx}` : text

    // Build conversation context from existing history (skip system placeholder, last 20 messages)
    const priorMsgs = history
      .filter((m) => m.role !== 'system' && m.content && m.content !== 'Select a model and start chatting.')
      .slice(-20)
      .map((m) => ({ role: m.role === 'assistant' ? 'assistant' : 'user', content: m.content }))
    const apiMessages = [...priorMsgs, { role: 'user', content: text }]

    setHistory((h) => [...h, { role: 'user', content: userDisplay }])
    setHistory((h) => [...h, { role: 'assistant', content: '' }])
    setBusy(true)
    setGenStatus(forceFast ? 'Entity analysis (fast)…' : 'Starting…')

    let searchCtx = ''
    if (useWebSearch) {
      let searchQ = text
      if (isEntityAsk && entityCtx) {
        const lines = entityCtx.split('\n')
        const title = lines[0].replace(/^Entity:\s*/, '').trim()
        const area = lines.find(l => /^AREA:/i.test(l))?.replace(/^AREA:\s*/i, '').trim() || ''
        const date = lines.find(l => /^DATE:/i.test(l))?.replace(/^DATE:\s*/i, '').trim() || ''
        const cat = lines.find(l => /^CATEGORY:/i.test(l))?.replace(/^CATEGORY:\s*/i, '').trim() || ''
        const parts = [title, cat, area, date].filter(Boolean)
        searchQ = parts.join(' ') || title || text
      }
      setGenStatus('🔍 DuckDuckGo search…')
      try {
        const sr = await fetchApi(`/api/search?q=${encodeURIComponent(searchQ)}&n=5`)
        const sd = await sr.json()
        if (sd.results && sd.results.length > 0) {
          searchCtx = sd.results.map((r: { title?: string; snippet?: string; url?: string }, i: number) =>
            `[${i + 1}] ${r.title}\n${r.snippet}\nURL: ${r.url}`
          ).join('\n\n')
        }
      } catch {
        // search failed silently, continue without context
      }
    }

    if (useCtx) setGenStatus('Loading situation picture (CTX)…')
    else if (useToolCalls) setGenStatus(`${provider} + tools — may take 30–90s…`)
    else if (forceFast) setGenStatus(`${provider} analyzing target…`)
    else setGenStatus(`Contacting ${provider}…`)

    const ac = new AbortController()
    abortRef.current = ac
    try {
      const r = await fetchApi('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'text/event-stream' },
        body: JSON.stringify({
          model: activeModel,
          messages: apiMessages,
          stream: true,
          context: useCtx,
          provider,
          entity_context: entityCtx || undefined,
          search_results: searchCtx || undefined,
          firewall,
          chat_session_id: getChatSessionId(),
          use_tools: useToolCalls,
          force_fast: forceFast,
          api_keys: apiKeys,
          api_base_urls: apiBaseUrls,
        }),
        signal: ac.signal,
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
                const existing = copy[copy.length - 1]?.content || ''
                const errMsg = 'Error: ' + data.error
                copy[copy.length - 1] = {
                  role: 'assistant',
                  content: existing ? `${existing}\n\n⚠ ${errMsg}` : errMsg,
                }
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
      if ((e as Error).name === 'AbortError') return
      setHistory((h) => {
        const copy = [...h]
        copy[copy.length - 1] = { role: 'assistant', content: 'Error: ' + (e as Error).message }
        return copy
      })
    } finally {
      abortRef.current = null
      setBusy(false)
      setGenStatus(null)
    }
  }

  const isOllama = provider === 'ollama'
  const ollamaCustomModels = customModels.ollama || []
  const activeProvider = providers.find((p) => p.id === provider)
  const providerModels = activeProvider?.models || []
  const customForProvider = customModels[provider] || []
  const cloudModelOptions = mergedModelsForProvider(provider, providerModels)
  const keyProviders = providers.filter((p) => p.requires_key)
  const keyMissing = Boolean(
    activeProvider?.requires_key && !activeProvider?.key_set && !(apiKeys[provider] || '').trim(),
  )

  return (
    <div className="panel chat">
      <h2>WorldBase AI</h2>

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
      {rerankerWarming && (
        <div className="chat-slow-hint" style={{ borderColor: '#ffd23f', color: '#ffd23f' }}>
          ⏳ Reranker warming up (ONNX/Torch) — first search may take a few extra seconds…
        </div>
      )}

      <div className="model-select">
        <select
          value={provider}
          onChange={(e) => {
            const pid = e.target.value
            setProvider(pid)
            try {
              localStorage.setItem(SELECTED_PROVIDER_KEY, pid)
            } catch {
              // ignore storage quota / privacy mode
            }
            setShowAddModel(false)
            setNewModelDraft('')
            const p = providers.find((x) => x.id === pid)
            if (pid === 'ollama') {
              if (models.length > 0) {
                const pick = pickModelForProvider('ollama', models.map((m) => m.name))
                setModel(pick || models[0].name)
              }
            } else {
              setModel(pickModelForProvider(pid, p?.models || []))
            }
          }}
          style={{ marginRight: 6 }}
        >
          {providers.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>

        {isOllama ? (
          <select
            value={model}
            onChange={(e) => {
              setModel(e.target.value)
              rememberSelectedModel('ollama', e.target.value)
            }}
            disabled={models.length === 0 && ollamaCustomModels.length === 0}
          >
            {models.length === 0 && ollamaCustomModels.length === 0 && modelsLoading && (
              <option value="">Loading models…</option>
            )}
            {models.length === 0 && ollamaCustomModels.length === 0 && !modelsLoading && (
              <option value="">No models found</option>
            )}
            {models.map((m) => (
              <option key={m.name} value={m.name}>
                {m.name} {m.parameter_size ? `(${m.parameter_size})` : ''}
              </option>
            ))}
            {ollamaCustomModels.length > 0 && (
              <optgroup label="Custom">
                {ollamaCustomModels.map((m) => (
                  <option key={`c-${m}`} value={m}>{m}</option>
                ))}
              </optgroup>
            )}
          </select>
        ) : (
          <>
            <select
              value={model || ''}
              onChange={(e) => {
                setModel(e.target.value)
                rememberSelectedModel(provider, e.target.value)
              }}
              disabled={cloudModelOptions.length === 0 && !model}
              style={{ maxWidth: 220, fontSize: 12 }}
            >
              {cloudModelOptions.length === 0 && !model && (
                <option value="">Add a custom model…</option>
              )}
              {model && !cloudModelOptions.includes(model) && (
                <option value={model}>{model}</option>
              )}
              {providerModels.length > 0 && (
                <optgroup label="Suggested">
                  {providerModels.map((m) => (
                    <option key={`s-${m}`} value={m}>{m}</option>
                  ))}
                </optgroup>
              )}
              {customForProvider.length > 0 && (
                <optgroup label="Custom">
                  {customForProvider.map((m) => (
                    <option key={`c-${m}`} value={m}>{m}</option>
                  ))}
                </optgroup>
              )}
            </select>
          </>
        )}

        <button
          type="button"
          className={showAddModel ? 'web-search on' : 'web-search'}
          onClick={() => setShowAddModel((v) => !v)}
          title="Add custom model for active provider (or use CUSTOM MODELS in SETUP)"
        >
          + MODEL
        </button>

        <button
          className={useTools ? 'web-search on' : 'web-search'}
          onClick={() => setUseTools((v) => !v)}
          title="WorldBase tool rounds (situations, OSINT, globe, memory) — local + cloud models; slower but smarter"
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
        <button
          className={showSettings ? 'web-search on' : 'web-search'}
          onClick={() => setShowSettings((v) => !v)}
          title="Configure provider API keys and base URLs (stored in this browser only)"
          style={{ marginLeft: 6 }}
        >
          ⚙ SETUP
        </button>
      </div>

      {showAddModel && (
        <div className="chat-add-model">
          <input
            value={newModelDraft}
            onChange={(e) => setNewModelDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && newModelDraft.trim()) {
                if (addCustomModelsFromDraft(provider, newModelDraft)) {
                  setNewModelDraft('')
                  setShowAddModel(false)
                }
              }
            }}
            placeholder={customModelPlaceholder(provider)}
            spellCheck={false}
          />
          <button
            type="button"
            disabled={!newModelDraft.trim()}
            onClick={() => {
              if (addCustomModelsFromDraft(provider, newModelDraft)) {
                setNewModelDraft('')
                setShowAddModel(false)
              }
            }}
          >
            ADD
          </button>
          <button type="button" className="web-search" onClick={() => { setShowAddModel(false); setNewModelDraft('') }}>
            CANCEL
          </button>
        </div>
      )}

      {keyMissing && !showSettings && (
        <div className="data-error" style={{ borderColor: '#ffd23f', color: '#ffd23f' }}>
          No API key for {activeProvider?.name || provider}.{' '}
          <button
            type="button"
            className="web-search"
            style={{ fontSize: 10, marginLeft: 6 }}
            onClick={() => setShowSettings(true)}
          >
            ⚙ ADD KEY
          </button>
        </div>
      )}

      {showSettings && (
        <div className="chat-settings">
          <div className="chat-settings-head">PROVIDER CREDENTIALS</div>
          <div className="chat-settings-note">
            Stored in this browser (localStorage) and sent only to the local WorldBase backend.
            Leave blank to use the server <code>.env</code> value or the provider default base URL.
          </div>
          {keyProviders.map((p) => (
            <div key={p.id} className="chat-settings-provider">
              <div className="chat-settings-row">
                <label htmlFor={`key-${p.id}`}>
                  {p.name}
                  {p.key_set && <span className="chat-key-env" title="A key is set in server .env"> · key .env</span>}
                  {p.base_url_set && <span className="chat-key-env" title="A base URL is set in server .env"> · url .env</span>}
                </label>
                <input
                  id={`key-${p.id}`}
                  type="password"
                  autoComplete="off"
                  placeholder={p.key_set ? 'using .env key — override here' : `${p.id} API key`}
                  value={apiKeys[p.id] || ''}
                  onChange={(e) => saveApiKeys({ ...apiKeys, [p.id]: e.target.value })}
                />
                {(apiKeys[p.id] || '').trim() && (
                  <button
                    type="button"
                    className="web-search"
                    style={{ fontSize: 10 }}
                    title="Clear this key from the browser"
                    onClick={() => {
                      const next = { ...apiKeys }
                      delete next[p.id]
                      saveApiKeys(next)
                    }}
                  >
                    ✕
                  </button>
                )}
              </div>
              {p.default_base_url && (
                <div className="chat-settings-row chat-settings-row-url">
                  <label htmlFor={`base-${p.id}`}>Base URL</label>
                  <input
                    id={`base-${p.id}`}
                    type="url"
                    autoComplete="off"
                    spellCheck={false}
                    placeholder={
                      p.base_url_set
                        ? 'using .env base URL — override here'
                        : p.default_base_url
                    }
                    value={apiBaseUrls[p.id] || ''}
                    onChange={(e) => saveApiBaseUrls({ ...apiBaseUrls, [p.id]: e.target.value })}
                  />
                  {(apiBaseUrls[p.id] || '').trim() && (
                    <button
                      type="button"
                      className="web-search"
                      style={{ fontSize: 10 }}
                      title="Clear this base URL from the browser (use default)"
                      onClick={() => {
                        const next = { ...apiBaseUrls }
                        delete next[p.id]
                        saveApiBaseUrls(next)
                      }}
                    >
                      ✕
                    </button>
                  )}
                </div>
              )}
            </div>
          ))}
          <div className="chat-settings-head" style={{ marginTop: 12 }}>CUSTOM MODELS</div>
          <div className="chat-settings-note">
            Saved per provider in this browser. Enter one slug or comma-separated list, then ADD
            (OpenRouter: <code>anthropic/claude-sonnet-4</code>).
          </div>
          {keyProviders.map((p) => {
            const list = customModels[p.id] || []
            const draft = customModelDrafts[p.id] || ''
            return (
              <div key={`custom-${p.id}`} className="chat-settings-provider">
                <div className="chat-settings-subhead">{p.name}</div>
                <div className="chat-settings-row chat-settings-row-model">
                  <input
                    id={`custom-model-${p.id}`}
                    type="text"
                    autoComplete="off"
                    spellCheck={false}
                    placeholder={customModelPlaceholder(p.id)}
                    value={draft}
                    onChange={(e) => setCustomModelDrafts({ ...customModelDrafts, [p.id]: e.target.value })}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && draft.trim()) {
                        addCustomModelsFromDraft(p.id, draft)
                      }
                    }}
                  />
                  <button
                    type="button"
                    disabled={!draft.trim()}
                    onClick={() => addCustomModelsFromDraft(p.id, draft)}
                  >
                    ADD
                  </button>
                </div>
                {list.length > 0 && (
                  <div className="chat-settings-chips">
                    {list.map((m) => (
                      <span key={m} className="chat-settings-chip">
                        <span>{m}</span>
                        <button
                          type="button"
                          title="Remove custom model"
                          onClick={() => removeCustomModel(p.id, m)}
                        >
                          ✕
                        </button>
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )
          })}
          <div className="chat-settings-provider">
            <div className="chat-settings-subhead">Ollama (local)</div>
            <div className="chat-settings-row chat-settings-row-model">
              <input
                id="custom-model-ollama"
                type="text"
                autoComplete="off"
                spellCheck={false}
                placeholder="qwen3:8b or my-local-model"
                value={customModelDrafts.ollama || ''}
                onChange={(e) => setCustomModelDrafts({ ...customModelDrafts, ollama: e.target.value })}
                onKeyDown={(e) => {
                  const draft = customModelDrafts.ollama || ''
                  if (e.key === 'Enter' && draft.trim()) {
                    addCustomModelsFromDraft('ollama', draft)
                  }
                }}
              />
              <button
                type="button"
                disabled={!(customModelDrafts.ollama || '').trim()}
                onClick={() => addCustomModelsFromDraft('ollama', customModelDrafts.ollama || '')}
              >
                ADD
              </button>
            </div>
            {(customModels.ollama || []).length > 0 && (
              <div className="chat-settings-chips">
                {(customModels.ollama || []).map((m) => (
                  <span key={m} className="chat-settings-chip">
                    <span>{m}</span>
                    <button type="button" title="Remove custom model" onClick={() => removeCustomModel('ollama', m)}>
                      ✕
                    </button>
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

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
        {busy ? (
          <button onClick={stopGeneration} className="chat-stop-btn">
            ⏹ Stop
          </button>
        ) : (
          <>
            <button onClick={() => sendWithMessage(msg.trim())} disabled={!model}>
              Send
            </button>
            {history.length > 1 && (
              <button
                onClick={() => setHistory([{ role: 'system', content: 'Select a model and start chatting.' }])}
                className="chat-clear-btn"
                title="Clear conversation context"
              >
                🗑
              </button>
            )}
          </>
        )}
      </div>
    </div>
  )
}

