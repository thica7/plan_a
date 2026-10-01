import { useContext, type MouseEvent } from 'react';
import { UNSAFE_LocationContext, UNSAFE_NavigationContext } from 'react-router-dom';
import { flushSync } from 'react-dom';

/** Keep repeated report IDs local to their reader and preserve its route. */
export function useReportAnchorJump() {
  const routing = useContext(UNSAFE_NavigationContext);
  const location = useContext(UNSAFE_LocationContext)?.location;
  return (event: MouseEvent<HTMLAnchorElement>, href: string | undefined, reveal?: () => void) => {
    if (!href?.startsWith('#')) return;
    const scope = event.currentTarget.closest('.run-report-review-studio') ?? event.currentTarget.closest('[data-report-scope]');
    if (!scope) return;
    event.preventDefault();
    let id: string;
    try { id = decodeURIComponent(href.slice(1)); } catch { return; }
    const target = Array.from(scope.querySelectorAll<HTMLElement>('[id]')).find(element => element.id === id);
    if (!target) return;
    const route = location ?? window.location;
    const next = { pathname: route.pathname, search: route.search, hash: href };
    flushSync(() => {
      reveal?.();
      if (routing) routing.navigator.replace(next, null);
      else window.history.replaceState(null, '', next.pathname + next.search + next.hash);
    });
    // Rendering a layer or revealing its trace can replace Markdown nodes.
    const visibleTarget = Array.from(scope.querySelectorAll<HTMLElement>('[id]')).find(element => element.id === id);
    visibleTarget?.scrollIntoView({ behavior: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'nearest' });
  };
}
