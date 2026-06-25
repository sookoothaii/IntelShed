/**
 * Hotkey Help overlay (J6) — shows all keyboard shortcuts.
 *
 * Opens with `?` key, closes with `Esc`.
 */

import type { HotkeyEntry } from "../hooks/useHotkeys";
import { isMac } from "../hooks/useHotkeys";

interface HotkeyHelpProps {
  open: boolean;
  onClose: () => void;
  entries: HotkeyEntry[];
}

function formatKey(entry: HotkeyEntry): string {
  const parts: string[] = [];
  if (entry.ctrl || entry.meta) {
    parts.push(isMac ? "⌘" : "Ctrl");
  }
  if (entry.shift) parts.push("Shift");
  if (entry.alt) parts.push("Alt");
  parts.push(entry.key === " " ? "Space" : entry.key);
  return parts.join(isMac ? "" : "+");
}

export function HotkeyHelp({ open, onClose, entries }: HotkeyHelpProps) {
  if (!open) return null;

  // Group by category
  const categories = new Map<string, HotkeyEntry[]>();
  for (const entry of entries) {
    if (!categories.has(entry.category)) {
      categories.set(entry.category, []);
    }
    categories.get(entry.category)!.push(entry);
  }

  const categoryLabels: Record<string, string> = {
    Navigation: "Navigation",
    Globe: "Globe",
    Chat: "Chat",
    System: "System",
    View: "View",
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
        background: "rgba(0,0,0,0.5)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
      onClick={onClose}
    >
      <div
        style={{
          width: "90%",
          maxWidth: 500,
          maxHeight: "80vh",
          overflowY: "auto",
          background: "#0f172a",
          border: "1px solid #334155",
          borderRadius: 12,
          boxShadow: "0 25px 50px -12px rgba(0,0,0,0.8)",
          padding: 24,
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginBottom: 20,
          }}
        >
          <h2 style={{ margin: 0, color: "#e2e8f0", fontSize: 18 }}>
            Keyboard Shortcuts
          </h2>
          <button
            onClick={onClose}
            style={{
              background: "transparent",
              border: "1px solid #334155",
              borderRadius: 6,
              color: "#94a3b8",
              padding: "4px 10px",
              cursor: "pointer",
              fontSize: 12,
            }}
          >
            Esc
          </button>
        </div>

        {Array.from(categories.entries()).map(([category, items]) => (
          <div key={category} style={{ marginBottom: 20 }}>
            <div
              style={{
                color: "#3b82f6",
                fontSize: 11,
                fontWeight: 700,
                textTransform: "uppercase",
                marginBottom: 8,
                letterSpacing: 0.5,
              }}
            >
              {categoryLabels[category] || category}
            </div>
            {items.map((entry, i) => (
              <div
                key={`${category}-${i}`}
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  padding: "6px 0",
                }}
              >
                <span style={{ color: "#cbd5e1", fontSize: 13 }}>
                  {entry.description}
                </span>
                <kbd
                  style={{
                    background: "#1e293b",
                    border: "1px solid #334155",
                    borderRadius: 4,
                    padding: "2px 8px",
                    color: "#94a3b8",
                    fontSize: 12,
                    fontFamily: "monospace",
                  }}
                >
                  {formatKey(entry)}
                </kbd>
              </div>
            ))}
          </div>
        ))}

        <div
          style={{
            marginTop: 16,
            paddingTop: 16,
            borderTop: "1px solid #1e293b",
            color: "#475569",
            fontSize: 11,
            textAlign: "center",
          }}
        >
          Press <kbd style={{ background: "#1e293b", borderRadius: 3, padding: "1px 6px" }}>?</kbd> to toggle this help
        </div>
      </div>
    </div>
  );
}
