import { create } from 'zustand';
import { WsTickPayload, WsEventPayload, ScheduleResponse } from '../types';

interface TelemetryState {
  connected: boolean;
  currentTick: WsTickPayload | null;
  history: WsTickPayload[];
  events: WsEventPayload[];
  activeSchedule: ScheduleResponse | null;
  isConnecting: boolean;
  error: string | null;

  // Actions
  connectWebSocket: () => void;
  disconnectWebSocket: () => void;
  setSpeed: (speed: number) => Promise<void>;
  pauseSim: () => Promise<void>;
  resumeSim: (speed?: number) => Promise<void>;
  stepSim: (seconds?: number) => Promise<void>;
  fetchLatestSchedule: () => Promise<void>;
  fetchRecentEvents: () => Promise<void>;
}

let wsInstance: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

const MAX_HISTORY_POINTS = 1440; // up to 24-48 hours (thinned/buffered)
const MAX_EVENTS = 50;

export const useTelemetryStore = create<TelemetryState>((set, get) => ({
  connected: false,
  currentTick: null,
  history: [],
  events: [],
  activeSchedule: null,
  isConnecting: false,
  error: null,

  connectWebSocket: () => {
    if (wsInstance && (wsInstance.readyState === WebSocket.OPEN || wsInstance.readyState === WebSocket.CONNECTING)) {
      return;
    }

    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }

    set({ isConnecting: true, error: null });

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    const wsUrl = `${protocol}//${host}/ws/telemetry`;

    try {
      const ws = new WebSocket(wsUrl);
      wsInstance = ws;

      ws.onopen = () => {
        set({ connected: true, isConnecting: false, error: null });
        get().fetchLatestSchedule();
        get().fetchRecentEvents();
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);

          if (data.type === 'tick') {
            const tick = data as WsTickPayload;
            set((state) => {
              const newHistory = [...state.history, tick];
              if (newHistory.length > MAX_HISTORY_POINTS) {
                newHistory.shift();
              }
              return {
                currentTick: tick,
                history: newHistory,
              };
            });
          } else if (data.type === 'event') {
            const ev = data as WsEventPayload;
            set((state) => ({
              events: [ev, ...state.events].slice(0, MAX_EVENTS),
            }));

            // If schedule created, reload schedule
            if (ev.event === 'SCHEDULE_CREATED') {
              get().fetchLatestSchedule();
            }
          }
        } catch {
          // ignore non-json messages like pings
        }
      };

      ws.onclose = () => {
        set({ connected: false, isConnecting: false });
        wsInstance = null;
        // Auto-reconnect after 2 seconds
        reconnectTimer = setTimeout(() => {
          get().connectWebSocket();
        }, 2000);
      };

      ws.onerror = () => {
        set({ connected: false, error: 'WebSocket connection error' });
        ws.close();
      };
    } catch (err) {
      set({
        connected: false,
        isConnecting: false,
        error: err instanceof Error ? err.message : 'Unknown WS error',
      });
    }
  },

  disconnectWebSocket: () => {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    if (wsInstance) {
      wsInstance.close();
      wsInstance = null;
    }
    set({ connected: false, isConnecting: false });
  },

  setSpeed: async (speed: number) => {
    try {
      await fetch('/api/sim/control', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'speed', speed }),
      });
    } catch (err) {
      console.error('Failed to set speed:', err);
    }
  },

  pauseSim: async () => {
    try {
      await fetch('/api/sim/control', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'pause' }),
      });
    } catch (err) {
      console.error('Failed to pause:', err);
    }
  },

  resumeSim: async (speed?: number) => {
    try {
      await fetch('/api/sim/control', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'resume', speed }),
      });
    } catch (err) {
      console.error('Failed to resume:', err);
    }
  },

  stepSim: async (step_seconds = 60) => {
    try {
      await fetch('/api/sim/control', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'step', step_seconds }),
      });
    } catch (err) {
      console.error('Failed to step:', err);
    }
  },

  fetchLatestSchedule: async () => {
    try {
      const res = await fetch('/api/schedules?limit=1');
      if (res.ok) {
        const list = await res.json();
        if (list && list.length > 0) {
          const detailRes = await fetch(`/api/schedules/${list[0].id}`);
          if (detailRes.ok) {
            const detail = await detailRes.json();
            set({ activeSchedule: detail });
          }
        }
      }
    } catch (err) {
      console.debug('Failed to fetch schedule:', err);
    }
  },

  fetchRecentEvents: async () => {
    try {
      const res = await fetch('/api/events?limit=30');
      if (res.ok) {
        const events = await res.json();
        if (Array.isArray(events)) {
          set({ events: events.reverse() });
        }
      }
    } catch (err) {
      console.debug('Failed to fetch events:', err);
    }
  },
}));
