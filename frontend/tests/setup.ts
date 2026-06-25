import '@testing-library/jest-dom/vitest'
import { afterEach, vi, beforeAll } from 'vitest'
import { cleanup } from '@testing-library/react'

// Polyfill localStorage/sessionStorage — jsdom's implementation is incomplete
beforeAll(() => {
  const makeStorage = () => {
    const store = new Map<string, string>()
    return {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => store.set(k, String(v)),
      removeItem: (k: string) => store.delete(k),
      clear: () => store.clear(),
      key: (i: number) => Array.from(store.keys())[i] ?? null,
      get length() { return store.size },
    }
  }
  Object.defineProperty(globalThis, 'localStorage', { value: makeStorage(), configurable: true })
  Object.defineProperty(globalThis, 'sessionStorage', { value: makeStorage(), configurable: true })
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  localStorage.clear()
  sessionStorage.clear()
})

// Polyfill matchMedia for components that check prefers-color-scheme
if (!window.matchMedia) {
  window.matchMedia = (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })
}

// Stub import.meta.env for tests
vi.stubEnv('VITE_WORLDBASE_API_KEY', '')
vi.stubEnv('VITE_WORLDBASE_AGENT_BUS', '')
vi.stubEnv('VITE_CESIUM_ION_TOKEN', '')
