import { apiIdentityHeaders } from './http';

/** Explicit request scope does not replace the identity used by server permission checks. */
export function workspaceIdForSearch(search: string): string {
  return new URLSearchParams(search).get('workspace_id')?.trim()
    || apiIdentityHeaders()['X-Workspace-Id']?.trim()
    || 'default-workspace';
}

export function workspaceSearch(workspaceId: string): string {
  return `?${new URLSearchParams({ workspace_id: workspaceId })}`;
}
