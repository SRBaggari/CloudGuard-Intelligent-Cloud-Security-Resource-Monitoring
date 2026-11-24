import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, tokens } from "./api";

/** Fetch JSON from the API with loading/error state, optional polling and manual reload. */
export function useApi<T>(path: string | null, opts: { interval?: number; query?: Record<string, unknown> } = {}) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState<boolean>(!!path);
  const queryKey = JSON.stringify(opts.query ?? {});
  const tick = useRef(0);

  const load = useCallback(
    async (silent = false) => {
      if (!path) return;
      const id = ++tick.current;
      if (!silent) setLoading(true);
      try {
        const res = await api<T>(path, { query: JSON.parse(queryKey) });
        if (id === tick.current) {
          setData(res);
          setError(null);
        }
      } catch (e) {
        if (id === tick.current) setError(e instanceof ApiError ? e : new ApiError(0, String(e)));
      } finally {
        if (id === tick.current) setLoading(false);
      }
    },
    [path, queryKey],
  );

  useEffect(() => {
    load();
    if (!opts.interval) return;
    const t = setInterval(() => load(true), opts.interval);
    return () => clearInterval(t);
  }, [load, opts.interval]);

  return { data, error, loading, reload: () => load(true), setData };
}

/** Subscribe to a CloudGuard WebSocket channel with automatic reconnect. */
export function useLiveChannel(channel: "monitoring" | "alerts" | "notifications", onMessage: (msg: any) => void) {
  const handler = useRef(onMessage);
  handler.current = onMessage;
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;
    let retry: ReturnType<typeof setTimeout>;
    let ping: ReturnType<typeof setInterval>;
    const connect = () => {
      const token = tokens.access;
      if (!token || closed) return;
      const proto = location.protocol === "https:" ? "wss:" : "ws:";
      ws = new WebSocket(`${proto}//${location.host}/ws/${channel}?token=${encodeURIComponent(token)}`);
      ws.onopen = () => {
        setConnected(true);
        ping = setInterval(() => ws?.readyState === 1 && ws.send("ping"), 25000);
      };
      ws.onmessage = (e) => {
        try {
          handler.current(JSON.parse(e.data));
        } catch {
          /* ignore malformed */
        }
      };
      ws.onclose = () => {
        setConnected(false);
        clearInterval(ping);
        if (!closed) retry = setTimeout(connect, 3000);
      };
    };
    connect();
    return () => {
      closed = true;
      clearTimeout(retry);
      clearInterval(ping);
      ws?.close();
    };
  }, [channel]);

  return connected;
}

/** Notify other components (e.g. the top-bar bell) that notification read-state changed. */
export const NOTIFICATIONS_CHANGED = "cg:notifications-changed";
export const emitNotificationsChanged = () => window.dispatchEvent(new Event(NOTIFICATIONS_CHANGED));
