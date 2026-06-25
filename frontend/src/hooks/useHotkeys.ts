/**
 * Global keyboard shortcuts hook (J6).
 *
 * Zero dependencies, zero bundle impact.
 * Hotkeys: 1-8 tabs, G focus globe, F fullscreen, R refresh, Esc close,
 * Ctrl+K command palette, Ctrl+Enter send chat, ? help.
 */

import { useEffect, useCallback, useState } from "react";

export interface HotkeyConfig {
  key: string;
  ctrl?: boolean;
  meta?: boolean;
  shift?: boolean;
  alt?: boolean;
  action: () => void;
  description: string;
  category: string;
}

export interface HotkeyEntry {
  key: string;
  ctrl?: boolean;
  meta?: boolean;
  shift?: boolean;
  alt?: boolean;
  description: string;
  category: string;
}

const isMac = typeof navigator !== "undefined" && navigator.platform.includes("Mac");

function matchesModifier(
  e: KeyboardEvent,
  cfg: { ctrl?: boolean; meta?: boolean; shift?: boolean; alt?: boolean },
): boolean {
  const cmd = isMac ? e.metaKey : e.ctrlKey;
  if (cfg.ctrl || cfg.meta) {
    if (!cmd) return false;
  } else {
    if (cmd) return false;
  }
  if (cfg.shift && !e.shiftKey) return false;
  if (!cfg.shift && e.shiftKey) return false;
  if (cfg.alt && !e.altKey) return false;
  if (!cfg.alt && e.altKey) return false;
  return true;
}

export function useHotkeys(
  configs: HotkeyConfig[],
  options: { enableInInput?: boolean } = {},
) {
  const { enableInInput = false } = options;
  const [helpOpen, setHelpOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      // Don't intercept in input fields unless explicitly enabled
      const target = e.target as HTMLElement;
      const inInput =
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.contentEditable === "true");

      // Ctrl+K / Cmd+K always works
      const cmd = isMac ? e.metaKey : e.ctrlKey;
      if (cmd && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((prev) => !prev);
        return;
      }

      // ? shows help (shift+/)
      if (e.key === "?" && !inInput) {
        e.preventDefault();
        setHelpOpen((prev) => !prev);
        return;
      }

      // Esc closes overlays
      if (e.key === "Escape") {
        if (helpOpen) {
          setHelpOpen(false);
          e.preventDefault();
          return;
        }
        if (paletteOpen) {
          setPaletteOpen(false);
          e.preventDefault();
          return;
        }
      }

      if (inInput && !enableInInput) {
        // Ctrl+Enter in chat input
        if (cmd && e.key === "Enter") {
          const cfg = configs.find(
            (c) => c.ctrl && c.key.toLowerCase() === "enter",
          );
          if (cfg) {
            e.preventDefault();
            cfg.action();
          }
        }
        return;
      }

      // Match configs
      for (const cfg of configs) {
        if (e.key.toLowerCase() === cfg.key.toLowerCase() && matchesModifier(e, cfg)) {
          e.preventDefault();
          cfg.action();
          return;
        }
      }
    },
    [configs, enableInInput, helpOpen, paletteOpen],
  );

  useEffect(() => {
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);

  return {
    helpOpen,
    setHelpOpen,
    paletteOpen,
    setPaletteOpen,
  };
}

export function getHotkeyList(configs: HotkeyConfig[]): HotkeyEntry[] {
  return configs.map((c) => ({
    key: c.key,
    ctrl: c.ctrl,
    meta: c.meta,
    shift: c.shift,
    alt: c.alt,
    description: c.description,
    category: c.category,
  }));
}

export { isMac };
