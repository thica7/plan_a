const AUTH_TOKEN_STORAGE_KEY = "competiscope.authToken";
const USER_ID_STORAGE_KEY = "competiscope.userId";
const USER_ROLE_STORAGE_KEY = "competiscope.userRole";
const WORKSPACE_ID_STORAGE_KEY = "competiscope.workspaceId";

export function apiIdentityHeaders(): Record<string, string> {
  const headers: Record<string, string> = {};
  const token = envValue("VITE_API_BEARER_TOKEN") || storageValue(AUTH_TOKEN_STORAGE_KEY);
  const userId = envValue("VITE_API_USER_ID") || storageValue(USER_ID_STORAGE_KEY);
  const userRole = envValue("VITE_API_USER_ROLE") || storageValue(USER_ROLE_STORAGE_KEY);
  const workspaceId =
    envValue("VITE_API_WORKSPACE_ID") || storageValue(WORKSPACE_ID_STORAGE_KEY);

  if (token) headers.Authorization = `Bearer ${token}`;
  if (userId) headers["X-User-Id"] = userId;
  if (userRole) headers["X-User-Role"] = userRole;
  if (workspaceId) headers["X-Workspace-Id"] = workspaceId;
  return headers;
}

function envValue(name: string): string {
  const env = (import.meta as ImportMeta & { env?: Record<string, string | undefined> }).env;
  return env?.[name]?.trim() ?? "";
}

function storageValue(key: string): string {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem(key)?.trim() ?? "";
}

export function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  if (!path.startsWith('/api/')) return Promise.reject(new Error('Only local API paths are allowed'));
  const headers = new Headers(apiIdentityHeaders());
  new Headers(init?.headers).forEach((value, key) => headers.set(key, value));
  return fetch(path, { ...init, headers, credentials: 'same-origin' });
}
