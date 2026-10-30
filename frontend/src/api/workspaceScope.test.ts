import { beforeEach, expect, it } from 'vitest';
import { workspaceIdForSearch, workspaceSearch } from './workspaceScope';

beforeEach(() => { localStorage.removeItem('competiscope.workspaceId'); });

it('prefers explicit URL scope without changing authenticated identity headers', () => {
  localStorage.setItem('competiscope.workspaceId', 'identity-space');
  expect(workspaceIdForSearch('?workspace_id=selected%2Fspace')).toBe('selected/space');
  expect(localStorage.getItem('competiscope.workspaceId')).toBe('identity-space');
});
it('uses identity scope for missing or whitespace-only URL scope, then the default', () => {
  localStorage.setItem('competiscope.workspaceId', 'identity-space');
  expect(workspaceIdForSearch('')).toBe('identity-space');
  expect(workspaceIdForSearch('?workspace_id=%20%20')).toBe('identity-space');
  localStorage.removeItem('competiscope.workspaceId');
  expect(workspaceIdForSearch('')).toBe('default-workspace');
});
it('round-trips opaque workspace values through request scope links', () => {
  const workspace = '空间 / + & =';
  expect(workspaceIdForSearch(workspaceSearch(workspace))).toBe(workspace);
});
