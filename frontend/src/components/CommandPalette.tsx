/**
 * Command Palette (J6) — Ctrl+K fuzzy search.
 *
 * Searches feeds, entities, and actions. Zero external dependency —
 * uses simple substring + fuzzy matching.
 */

import { useEffect, useState, useMemo, useRef } from "react";
import { isMac } from "../hooks/useHotkeys";

interface CommandItem {
  id: string;
  label: string;
  description?: string;
  category: "feed" | "entity" | "action";
  onSelect: () => void;
}

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
  onFlyTo?: (lat: number, lon: number, title?: string) => void;
  onGenerateBriefing?: () => void;
  onToggleLayer?: (layer: string) => void;
  onSwitchTab?: (tab: string) => void;
}

function fuzzyMatch(query: string, text: string): boolean {
  if (!query) return true;
  const q = query.toLowerCase();
  const t = text.toLowerCase();
  if (t.includes(q)) return true;
  // Fuzzy: check if all chars appear in order
  let qi = 0;
  for (let ti = 0; ti < t.length && qi < q.length; ti++) {
    if (t[ti] === q[qi]) qi++;
  }
  return qi === q.length;
}

export function CommandPalette({
  open,
  onClose,
  onFlyTo,
  onGenerateBriefing,
  onToggleLayer,
  onSwitchTab,
}: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [feeds, setFeeds] = useState<CommandItem[]>([]);
  const [entities, setEntities] = useState<CommandItem[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  // Built-in actions
  const actions: CommandItem[] = useMemo(() => {
    const items: CommandItem[] = [
      {
        id: "action-briefing",
        label: "Generate Briefing",
        description: "Force generate a new intelligence briefing",
        category: "action",
        onSelect: () => {
          onGenerateBriefing?.();
          onClose();
        },
      },
      {
        id: "action-tab-globe",
        label: "Switch to Globe",
        description: "Navigate to 3D globe view",
        category: "action",
        onSelect: () => {
          onSwitchTab?.("globe");
          onClose();
        },
      },
      {
        id: "action-tab-map",
        label: "Switch to Map",
        description: "Navigate to 2D map view",
        category: "action",
        onSelect: () => {
          onSwitchTab?.("map");
          onClose();
        },
      },
      {
        id: "action-tab-data",
        label: "Switch to Data",
        description: "Navigate to data panel",
        category: "action",
        onSelect: () => {
          onSwitchTab?.("data");
          onClose();
        },
      },
      {
        id: "action-tab-chat",
        label: "Switch to AI Chat",
        description: "Navigate to AI chat panel",
        category: "action",
        onSelect: () => {
          onSwitchTab?.("chat");
          onClose();
        },
      },
      {
        id: "action-tab-situations",
        label: "Switch to Situations",
        description: "Navigate to situation board",
        category: "action",
        onSelect: () => {
          onSwitchTab?.("situations");
          onClose();
        },
      },
    ];

    // Layer toggles
    const layers = [
      "aircraft", "quakes", "events", "maritime", "intelFt",
      "weather", "wildfires", "lightning", "geopolitics",
    ];
    for (const layer of layers) {
      items.push({
        id: `action-layer-${layer}`,
        label: `Toggle ${layer} layer`,
        description: `Enable/disable the ${layer} globe layer`,
        category: "action",
        onSelect: () => {
          onToggleLayer?.(layer);
          onClose();
        },
      });
    }

    // Fly-to presets
    const presets: Array<{ name: string; lat: number; lon: number }> = [
      { name: "Bangkok", lat: 13.7563, lon: 100.5018 },
      { name: "Myanmar Border", lat: 16.8, lon: 98.4 },
      { name: "Taiwan Strait", lat: 24.5, lon: 119.5 },
      { name: "South China Sea", lat: 12.0, lon: 114.0 },
      { name: "Ukraine", lat: 49.0, lon: 32.0 },
      { name: "Gaza", lat: 31.5, lon: 34.47 },
      { name: "Red Sea", lat: 15.0, lon: 41.0 },
    ];
    for (const p of presets) {
      items.push({
        id: `action-flyto-${p.name}`,
        label: `Fly to ${p.name}`,
        description: `Center globe on ${p.name}`,
        category: "action",
        onSelect: () => {
          onFlyTo?.(p.lat, p.lon, p.name);
          onClose();
        },
      });
    }

    return items;
  }, [onFlyTo, onGenerateBriefing, onToggleLayer, onSwitchTab, onClose]);

  // Fetch feeds when palette opens
  useEffect(() => {
    if (!open) return;
    setQuery("");
    setSelectedIndex(0);
    inputRef.current?.focus();

    // Fetch connectors
    fetch("/api/connectors")
      .then((r) => r.json())
      .then((data) => {
        const items: CommandItem[] = (data.connectors || []).map((c: Record<string, unknown>) => ({
          id: `feed-${c.name || c.id}`,
          label: String(c.name || c.id || "unknown"),
          description: String(c.description || c.category || ""),
          category: "feed" as const,
          onSelect: () => {
            onSwitchTab?.("data");
            onClose();
          },
        }));
        setFeeds(items);
      })
      .catch(() => {});

    // Fetch geolocated entities
    fetch("/api/intel/entities?geolocated=1&limit=50")
      .then((r) => r.json())
      .then((data) => {
        const items: CommandItem[] = (data.entities || []).map((e: Record<string, unknown>) => ({
          id: `entity-${e.id}`,
          label: String(e.caption || e.id || "unknown"),
          description: String(e.schema || ""),
          category: "entity" as const,
          onSelect: () => {
            const lat = Number(e.lat);
            const lon = Number(e.lon);
            if (lat && lon) {
              onFlyTo?.(lat, lon, String(e.caption || e.id));
            }
            onClose();
          },
        }));
        setEntities(items);
      })
      .catch(() => {});
  }, [open, onClose, onFlyTo, onSwitchTab]);

  // Filter items
  const allItems = useMemo(
    () => [...actions, ...feeds, ...entities],
    [actions, feeds, entities],
  );

  const filtered = useMemo(
    () => allItems.filter((item) => fuzzyMatch(query, item.label)),
    [allItems, query],
  );

  // Keyboard navigation
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedIndex((i) => Math.min(i + 1, filtered.length - 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedIndex((i) => Math.max(i - 1, 0));
      } else if (e.key === "Enter") {
        e.preventDefault();
        filtered[selectedIndex]?.onSelect();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, filtered, selectedIndex]);

  if (!open) return null;

  const categoryColors: Record<string, string> = {
    feed: "#3b82f6",
    entity: "#10b981",
    action: "#f59e0b",
  };

  return (
    <div
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        zIndex: 9999,
        background: "rgba(0,0,0,0.4)",
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "center",
        paddingTop: "15vh",
      }}
      onClick={onClose}
    >
      <div
        style={{
          width: "90%",
          maxWidth: 600,
          background: "#0f172a",
          border: "1px solid #334155",
          borderRadius: 12,
          boxShadow: "0 25px 50px -12px rgba(0,0,0,0.8)",
          overflow: "hidden",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setSelectedIndex(0);
          }}
          placeholder="Search feeds, entities, actions..."
          style={{
            width: "100%",
            padding: "16px 20px",
            background: "transparent",
            border: "none",
            borderBottom: "1px solid #1e293b",
            color: "#e2e8f0",
            fontSize: 16,
            outline: "none",
            boxSizing: "border-box",
          }}
        />
        <div style={{ maxHeight: 400, overflowY: "auto" }}>
          {filtered.length === 0 && (
            <div style={{ padding: 20, color: "#64748b", textAlign: "center" }}>
              No results found
            </div>
          )}
          {filtered.map((item, i) => (
            <div
              key={item.id}
              onClick={() => item.onSelect()}
              onMouseEnter={() => setSelectedIndex(i)}
              style={{
                padding: "10px 20px",
                cursor: "pointer",
                background: i === selectedIndex ? "#1e293b" : "transparent",
                display: "flex",
                alignItems: "center",
                gap: 12,
              }}
            >
              <span
                style={{
                  fontSize: 10,
                  fontWeight: 700,
                  textTransform: "uppercase",
                  color: categoryColors[item.category],
                  minWidth: 50,
                }}
              >
                {item.category}
              </span>
              <div>
                <div style={{ color: "#e2e8f0", fontSize: 14 }}>{item.label}</div>
                {item.description && (
                  <div style={{ color: "#64748b", fontSize: 12 }}>{item.description}</div>
                )}
              </div>
            </div>
          ))}
        </div>
        <div
          style={{
            padding: "8px 20px",
            borderTop: "1px solid #1e293b",
            fontSize: 11,
            color: "#475569",
            display: "flex",
            gap: 16,
          }}
        >
          <span>↑↓ Navigate</span>
          <span>↵ Select</span>
          <span>Esc Close</span>
          <span style={{ marginLeft: "auto" }}>
            {isMac ? "⌘" : "Ctrl"}+K
          </span>
        </div>
      </div>
    </div>
  );
}
