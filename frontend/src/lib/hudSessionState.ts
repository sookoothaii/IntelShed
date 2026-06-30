import { useCallback, useState, type Dispatch, type SetStateAction } from 'react';

/** Tab / panel navigation — survives reload within the same browser tab only. */
export const HUD_SESSION_KEY = 'worldbase_hud_session_v1';

type Store = Record<string, unknown>;

export function readHudSessionStore(): Store {
  try {
    const raw = sessionStorage.getItem(HUD_SESSION_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as unknown;
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? (parsed as Store) : {};
  } catch {
    return {};
  }
}

export function writeHudSessionStore(store: Store): void {
  try {
    sessionStorage.setItem(HUD_SESSION_KEY, JSON.stringify(store));
  } catch {
    /* private mode / quota */
  }
}

export function readHudSessionField<T>(
  key: string,
  fallback: T,
  validate?: (v: unknown) => v is T,
): T {
  const v = readHudSessionStore()[key];
  if (validate) return validate(v) ? v : fallback;
  if (v !== undefined && v !== null) return v as T;
  return fallback;
}

export function writeHudSessionField(key: string, value: unknown): void {
  const store = readHudSessionStore();
  store[key] = value;
  writeHudSessionStore(store);
}

export function useHudSessionState<T>(
  key: string,
  initial: T,
  validate?: (v: unknown) => v is T,
): [T, Dispatch<SetStateAction<T>>] {
  const [state, setState] = useState<T>(() => readHudSessionField(key, initial, validate));

  const setPersisted = useCallback(
    (action: SetStateAction<T>) => {
      setState((prev) => {
        const next = typeof action === 'function' ? (action as (p: T) => T)(prev) : action;
        writeHudSessionField(key, next);
        return next;
      });
    },
    [key],
  );

  return [state, setPersisted];
}
