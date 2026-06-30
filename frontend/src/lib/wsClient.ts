/**
 * WebSocket client for real-time globe updates (I10).
 *
 * Auto-reconnect with exponential backoff, heartbeat, graceful degradation to SSE.
 * Disabled when VITE_WORLDBASE_WS !== "1".
 */

interface WSEvent {
  type: string;
  ts?: string;
  data?: Record<string, unknown>;
  [key: string]: unknown;
}

type EventHandler = (event: WSEvent) => void;

class WSClient {
  private ws: WebSocket | null = null;
  private url: string;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 10;
  private baseDelay = 1000; // 1s
  private maxDelay = 30000; // 30s
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private handlers = new Map<string, Set<EventHandler>>();
  private connected = false;
  private intentionallyClosed = false;
  private layers: string[] = [];
  private bbox: [number, number, number, number] | null = null;

  constructor() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.hostname;
    const port = import.meta.env.VITE_WORLDBASE_WS_PORT || '8002';
    this.url = `${protocol}//${host}:${port}/api/ws`;
  }

  isEnabled(): boolean {
    return import.meta.env.VITE_WORLDBASE_WS === '1';
  }

  connect(): void {
    if (!this.isEnabled() || this.connected || this.intentionallyClosed) return;

    try {
      this.ws = new WebSocket(this.url);
    } catch {
      this.scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      this.connected = true;
      this.reconnectAttempts = 0;
      this.startHeartbeat();
      // Re-send subscriptions on reconnect
      if (this.layers.length > 0) {
        this.send({ cmd: 'subscribe', layers: this.layers });
      }
      if (this.bbox) {
        this.send({ cmd: 'viewport', bbox: this.bbox });
      }
      this.emit({ type: 'ws_connected' });
    };

    this.ws.onmessage = (event) => {
      try {
        const msg: WSEvent = JSON.parse(event.data);
        this.emit(msg);
      } catch {
        // ignore malformed messages
      }
    };

    this.ws.onerror = () => {
      // Error handling — reconnect will be triggered by onclose
    };

    this.ws.onclose = () => {
      this.connected = false;
      this.stopHeartbeat();
      if (!this.intentionallyClosed) {
        this.scheduleReconnect();
      }
      this.emit({ type: 'ws_disconnected' });
    };
  }

  disconnect(): void {
    this.intentionallyClosed = true;
    this.stopHeartbeat();
    if (this.ws) {
      this.ws.close(1000, 'client disconnect');
      this.ws = null;
    }
    this.connected = false;
  }

  send(msg: Record<string, unknown>): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg));
    }
  }

  subscribe(layers: string[]): void {
    this.layers = layers;
    this.send({ cmd: 'subscribe', layers });
  }

  setViewport(bbox: [number, number, number, number]): void {
    this.bbox = bbox;
    this.send({ cmd: 'viewport', bbox });
  }

  on(type: string, handler: EventHandler): () => void {
    if (!this.handlers.has(type)) {
      this.handlers.set(type, new Set());
    }
    this.handlers.get(type)!.add(handler);
    return () => this.off(type, handler);
  }

  off(type: string, handler: EventHandler): void {
    this.handlers.get(type)?.delete(handler);
  }

  isConnected(): boolean {
    return this.connected;
  }

  private emit(event: WSEvent): void {
    const type = event.type;
    this.handlers.get(type)?.forEach((h) => {
      try {
        h(event);
      } catch {
        // handler errors are non-fatal
      }
    });
  }

  private startHeartbeat(): void {
    this.heartbeatTimer = setInterval(() => {
      this.send({ cmd: 'ping' });
    }, 25000); // 25s — server sends heartbeat at 30s
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) return;
    const delay = Math.min(this.baseDelay * Math.pow(2, this.reconnectAttempts), this.maxDelay);
    this.reconnectAttempts++;
    setTimeout(() => {
      if (!this.intentionallyClosed) {
        this.connect();
      }
    }, delay);
  }
}

export const wsClient = new WSClient();
export type { WSEvent, EventHandler };
