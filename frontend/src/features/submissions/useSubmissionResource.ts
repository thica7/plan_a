import { useCallback, useContext, useEffect, useRef, useState } from 'react';
import { WindowVisibilityContext } from '../desktop/windowVisibility';

export const submissionPollInterval = 4000;
interface ResourceState<T> { key: string; data: T | null; error: unknown; loading: boolean }

/** One request at a time. A failed request requires an explicit refresh. */
export function useSubmissionResource<T>(
  key: string,
  load: (signal: AbortSignal) => Promise<T>,
  enabled = true,
  shouldPoll: (data: T) => boolean = () => false,
) {
  const windowVisible = useContext(WindowVisibilityContext);
  const effectiveEnabled = enabled && windowVisible;
  const [state, setState] = useState<ResourceState<T>>({ key, data: null, error: null, loading: effectiveEnabled });
  const [revision, setRevision] = useState(0);
  const loader = useRef(load);
  const polling = useRef(shouldPoll);
  const replace = useRef<((data: T) => void) | null>(null);
  const failure = useRef<{ key: string; revision: number; error: unknown } | null>(null);
  loader.current = load;
  polling.current = shouldPoll;

  useEffect(() => {
    let disposed = false;
    let failed = failure.current?.key === key && failure.current.revision === revision;
    if (!failed) failure.current = null;
    let lastData: T | null = null;
    let generation = 0;
    let controller: AbortController | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const clearPending = () => {
      clearTimeout(timer);
      generation += 1;
      controller?.abort();
      controller = null;
    };
    const schedule = (data: T) => {
      if (effectiveEnabled && polling.current(data) && document.visibilityState !== 'hidden') timer = setTimeout(() => { void run(); }, submissionPollInterval);
    };
    const accept = (data: T) => {
      if (disposed) return;
      clearPending();
      failed = false;
      failure.current = null;
      lastData = data;
      setState({ key, data, error: null, loading: false });
      schedule(data);
    };
    async function run() {
      if (disposed || !effectiveEnabled || failed || controller || document.visibilityState === 'hidden') return;
      const token = ++generation;
      controller = new AbortController();
      setState(previous => ({ key, data: previous.key === key ? previous.data : null, error: null, loading: true }));
      try {
        const data = await loader.current(controller.signal);
        if (disposed || token !== generation) return;
        controller = null;
        failure.current = null;
        lastData = data;
        setState({ key, data, error: null, loading: false });
        schedule(data);
      } catch (error) {
        if (disposed || token !== generation) return;
        controller = null;
        failed = true;
        failure.current = { key, revision, error };
        setState(previous => ({ key, data: previous.key === key ? previous.data : null, error, loading: false }));
      }
    }
    const visibility = () => {
      if (document.visibilityState === 'hidden') {
        clearPending();
        setState(previous => previous.key === key ? { ...previous, loading: false } : previous);
      } else if (!failed && (lastData === null || polling.current(lastData))) void run();
    };
    replace.current = accept;
    if (effectiveEnabled) {
      if (failed) setState(previous => ({ key, data: previous.key === key ? previous.data : null, error: failure.current?.error, loading: false }));
      else void run();
      document.addEventListener('visibilitychange', visibility);
    } else {
      // Minimized windows keep local filters and the cached runtime projection mounted.
      setState(previous => enabled && previous.key === key
        ? { ...previous, loading: false }
        : { key, data: null, error: null, loading: false });
    }
    return () => {
      disposed = true;
      clearPending();
      replace.current = null;
      document.removeEventListener('visibilitychange', visibility);
    };
  }, [key, enabled, effectiveEnabled, revision]);

  const refresh = useCallback(() => setRevision(value => value + 1), []);
  const setData = useCallback((data: T) => replace.current?.(data), []);
  const current = state.key === key ? state : { key, data: null, error: null, loading: effectiveEnabled };
  return { ...current, refresh, setData };
}
