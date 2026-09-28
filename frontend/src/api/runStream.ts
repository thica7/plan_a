import { apiFetch } from './http';
import type { RunEvent } from './sse_types';

/** Bearer-authenticated SSE; native EventSource remains available for cookie sessions. */
export function openAuthorizedRunStream(runId: string, onEvent: (event: RunEvent) => void) {
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  let lastId = '';
  async function connect() {
    try {
      const response = await apiFetch(`/api/runs/${encodeURIComponent(runId)}/stream`, { signal: controller.signal, headers: lastId ? { 'Last-Event-ID': lastId } : {} });
      if (!response.ok || !response.body) throw new Error(`Stream unavailable: ${response.status}`);
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      try {
        while (!controller.signal.aborted) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          let match: RegExpExecArray | null;
          while ((match = /\r?\n\r?\n/.exec(buffer))) {
            const frame = buffer.slice(0, match.index);
            buffer = buffer.slice(match.index + match[0].length);
            const lines = frame.split(/\r?\n/);
            const data = lines.filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n');
            const id = lines.find(line => line.startsWith('id:'))?.slice(3).trim();
            if (id) lastId = id;
            if (data) onEvent(JSON.parse(data) as RunEvent);
          }
        }
      } finally { await reader.cancel().catch(() => undefined); reader.releaseLock(); }
    } catch { /* Reconnect while at least one visible or minimized window subscribes. */ }
    if (!controller.signal.aborted) timer = setTimeout(() => void connect(), 3000);
  }
  void connect();
  return () => { controller.abort(); if (timer) clearTimeout(timer); };
}
