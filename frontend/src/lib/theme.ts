export type ThemeId = 'cyber' | 'mss';

const STORAGE_KEY = 'worldbase-theme';
const DATA_ATTR = 'data-theme';

function resolveDefault(): ThemeId {
  const env = import.meta.env.VITE_UI_THEME;
  if (env === 'mss') return 'mss';
  return 'cyber';
}

export function getStoredTheme(): ThemeId {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (v === 'mss' || v === 'cyber') return v;
  } catch {
    /* SSR / privacy mode */
  }
  return resolveDefault();
}

export function applyTheme(theme: ThemeId): void {
  const el = document.documentElement;
  if (theme === 'mss') {
    el.setAttribute(DATA_ATTR, 'mss');
  } else {
    el.removeAttribute(DATA_ATTR);
  }
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    /* ignore */
  }
}

export function toggleTheme(current: ThemeId): ThemeId {
  const next: ThemeId = current === 'cyber' ? 'mss' : 'cyber';
  applyTheme(next);
  return next;
}

export function initTheme(): ThemeId {
  const t = getStoredTheme();
  applyTheme(t);
  return t;
}
