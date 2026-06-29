import { useCallback, useEffect, useRef, useState } from 'react';
import { mapIntent, geocodePlace, needsGeocoding, type IntentResult } from '../lib/intentMapper';
import { executeActions, type ActionExecutor, type GlobeAction } from '../lib/globeActions';
import type { POI } from '../lib/pois';
import type { VisionMode } from '../lib/visionShaders';

type ChatMsg = {
  role: 'user' | 'system';
  text: string;
  ts: number;
};

type Props = {
  flyTo: (poi: POI) => void;
  toggleLayer: (layer: string, enabled: boolean) => void;
  setHeatmap: (on: boolean) => void;
  setVision: (mode: VisionMode) => void;
};

const SUGGESTIONS = [
  'Show me earthquakes near Thailand',
  'Fly to Tehran',
  'Enable thermal vision',
  'Show wildfires and maritime',
  'Fly to Strait of Hormuz',
  'Show darkweb intelligence',
  'Enable fusion heatmap',
  'Zoom out to overview',
];

export function GlobeChat({ flyTo, toggleLayer, setHeatmap, setVision }: Props) {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<ChatMsg[]>([
    { role: 'system', text: 'Ask the Globe: type a natural language command to fly, filter layers, or change vision mode.', ts: Date.now() },
  ]);
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const execRef = useRef<ActionExecutor>({
    flyTo,
    toggleLayer: (layer, enabled) => toggleLayer(layer, enabled),
    setHeatmap,
    setVision: (mode) => setVision(mode as VisionMode),
  });
  execRef.current = {
    flyTo,
    toggleLayer: (layer, enabled) => toggleLayer(layer, enabled),
    setHeatmap,
    setVision: (mode) => setVision(mode as VisionMode),
  };

  const handleQuery = useCallback(async (query: string) => {
    if (!query.trim()) return;
    setMessages((prev) => [...prev, { role: 'user', text: query, ts: Date.now() }]);
    setInput('');
    setBusy(true);

    const result: IntentResult = mapIntent(query);

    // Handle geocoding fallback
    const geocodePlaceName = needsGeocoding(result.matched);
    if (geocodePlaceName) {
      const geo = await geocodePlace(geocodePlaceName);
      if (geo) {
        const flyAction: GlobeAction = {
          type: 'fly_to',
          lat: geo.lat,
          lon: geo.lon,
          height: 200000,
          title: geo.display_name,
        };
        executeActions([flyAction, ...result.actions], execRef.current);
        setMessages((prev) => [...prev, {
          role: 'system',
          text: `Flying to ${geo.display_name}. ${result.actions.length ? 'Also: ' + result.explanation : ''}`,
          ts: Date.now(),
        }]);
      } else {
        setMessages((prev) => [...prev, {
          role: 'system',
          text: `Could not geocode "${geocodePlaceName}". Try a more specific place name.`,
          ts: Date.now(),
        }]);
      }
    } else {
      executeActions(result.actions, execRef.current);
      setMessages((prev) => [...prev, {
        role: 'system',
        text: result.explanation,
        ts: Date.now(),
      }]);
    }

    setBusy(false);
  }, []);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleQuery(input);
    }
  };

  if (!open) {
    return (
      <button
        className="globe-chat-fab"
        onClick={() => setOpen(true)}
        title="Ask the Globe"
      >
        ASK GLOBE
      </button>
    );
  }

  return (
    <div className="globe-chat-overlay">
      <div className="globe-chat-header">
        <span className="globe-chat-title">ASK THE GLOBE</span>
        <button className="globe-chat-close" onClick={() => setOpen(false)}>×</button>
      </div>
      <div className="globe-chat-messages" ref={scrollRef}>
        {messages.map((m, i) => (
          <div key={i} className={`globe-chat-msg ${m.role}`}>
            {m.text}
          </div>
        ))}
        {busy && <div className="globe-chat-msg system globe-chat-busy">Processing...</div>}
      </div>
      <div className="globe-chat-suggestions">
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            className="globe-chat-suggestion"
            onClick={() => handleQuery(s)}
            disabled={busy}
          >
            {s}
          </button>
        ))}
      </div>
      <div className="globe-chat-input-row">
        <input
          className="globe-chat-input"
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="e.g. show me wildfires near Bangkok"
          disabled={busy}
          autoFocus
        />
        <button
          className="globe-chat-send"
          onClick={() => handleQuery(input)}
          disabled={busy || !input.trim()}
        >
          ➤
        </button>
      </div>
    </div>
  );
}
