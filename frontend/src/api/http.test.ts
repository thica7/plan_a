import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiFetch } from './http';

afterEach(() => { localStorage.clear(); vi.unstubAllGlobals(); });
describe('API identity', () => {
  it('sends stored bearer and workspace identity on knowledge requests', async () => {
    localStorage.setItem('competiscope.authToken', 'test-token');
    localStorage.setItem('competiscope.workspaceId', 'workspace-test');
    const fetcher = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal('fetch', fetcher);
    await apiFetch('/api/knowledge/documents/example', { method: 'DELETE' });
    const headers = new Headers(fetcher.mock.calls[0][1].headers);
    expect(headers.get('Authorization')).toBe('Bearer test-token');
    expect(headers.get('X-Workspace-Id')).toBe('workspace-test');
  });
  it('never sends stored identity to a remote URL', async () => {
    localStorage.setItem('competiscope.authToken', 'test-token');
    const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher);
    await expect(apiFetch('https://example.com')).rejects.toThrow('local API');
    expect(fetcher).not.toHaveBeenCalled();
  });
});


it('downloads artifact bytes through the authenticated local API and rejects failures', async () => {
  const { downloadArtifact } = await import('./client');
  localStorage.setItem('competiscope.authToken', 'download-token');
  const fetcher = vi.fn().mockResolvedValueOnce(new Response('正文')).mockResolvedValueOnce(new Response('Forbidden', { status: 403 }));
  vi.stubGlobal('fetch', fetcher);
  expect(await (await downloadArtifact('artifact/1')).text()).toBe('正文');
  expect(fetcher.mock.calls[0][0]).toBe('/api/enterprise/artifacts/artifact%2F1/download');
  expect(new Headers(fetcher.mock.calls[0][1].headers).get('Authorization')).toBe('Bearer download-token');
  await expect(downloadArtifact('artifact-2')).rejects.toThrow();
});
