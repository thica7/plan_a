import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { apiFetch, apiIdentityHeaders } from '../../api/http';

export interface KnowledgeWorkScope {
  projectId: string | null;
  includeWorkspaceLibrary: boolean;
}

export function knowledgeScopeUrl(path: string, scope: KnowledgeWorkScope, write = false) {
  const params = new URLSearchParams();
  if (scope.projectId) params.set('project_id', scope.projectId);
  params.set('include_workspace_library', String(!write && scope.includeWorkspaceLibrary));
  return `${path}${path.includes('?') ? '&' : '?'}${params}`;
}

interface ScopeProject { id: string; workspace_id: string; name: string }

export function useKnowledgeWorkScope() {
  const [params, setParams] = useSearchParams();
  const projectId = params.get('project_id');
  const includeWorkspaceLibrary = params.get('include_workspace_library') === 'true';
  const [projects, setProjects] = useState<ScopeProject[]>([]);
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const headers = apiIdentityHeaders();
    Promise.all(['/api/enterprise/workspaces', '/api/enterprise/projects'].map(async path => {
      const response = await apiFetch(path, { signal: controller.signal });
      if (!response.ok) throw new Error('项目范围加载失败，请重新打开页面重试。');
      return response.json();
    })).then(([workspaces, listed]) => {
      if (!active) return;
      // A bearer subject is scoped by the server. Never let a forged header select
      // another workspace from an unfiltered local-development project list.
      const currentWorkspace = headers.Authorization
        ? Array.isArray(workspaces) && workspaces.length === 1 ? workspaces[0].id : null
        : headers['X-Workspace-Id'] || 'default-workspace';
      if (!currentWorkspace) throw new Error('无法确认当前工作区，已暂停知识请求。');
      setWorkspaceId(currentWorkspace);
      setProjects(Array.isArray(listed) ? listed.filter(p => p.workspace_id === currentWorkspace) : []);
      setLoaded(true);
    }).catch(err => { if (active) setError(err instanceof Error ? err.message : '项目范围加载失败。'); });
    return () => { active = false; controller.abort(); };
  }, []);
  const invalidProject = loaded && projectId !== null && !projects.some(p => p.id === projectId);
  const scope = useMemo(() => ({ projectId, includeWorkspaceLibrary }), [projectId, includeWorkspaceLibrary]);
  const change = (next: Partial<KnowledgeWorkScope>) => {
    const updated = new URLSearchParams(params);
    if ('projectId' in next) {
      if (next.projectId) updated.set('project_id', next.projectId); else updated.delete('project_id');
    }
    if ('includeWorkspaceLibrary' in next) updated.set('include_workspace_library', String(next.includeWorkspaceLibrary));
    setParams(updated);
  };
  return { scope, projects, change, key: `${workspaceId ?? 'loading'}:${projectId ?? ''}:${includeWorkspaceLibrary}`,
    ready: loaded && !error && !invalidProject,
    error: error ?? (invalidProject ? '项目不存在或不属于当前工作区，请重新选择。' : null), loaded };
}

export function KnowledgeScopeControl({ value }: { value: ReturnType<typeof useKnowledgeWorkScope> }) {
  return <div className="flex flex-wrap items-center gap-3 rounded-lg border border-base-300 bg-base-100 p-3">
    <label>项目范围 <select className="input input-bordered input-sm" aria-label="项目范围" disabled={!value.loaded} value={value.scope.projectId ?? ''} onChange={e => value.change({ projectId: e.target.value || null })}>
      <option value="">工作区公共库</option>
      {value.scope.projectId && !value.projects.some(p => p.id === value.scope.projectId) ? <option value={value.scope.projectId}>无法访问的项目</option> : null}
      {value.projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}
    </select></label>
    <label className="flex items-center gap-2"><input type="checkbox" checked={value.scope.includeWorkspaceLibrary} disabled={!value.ready || !value.scope.projectId} onChange={e => value.change({ includeWorkspaceLibrary: e.target.checked })} />同时读取工作区公共库</label>
    {!value.loaded && !value.error ? <span role="status">正在加载项目范围…</span> : null}
    {value.error ? <p role="alert">{value.error}</p> : null}
  </div>;
}
