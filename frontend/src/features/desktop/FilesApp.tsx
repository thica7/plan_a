import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getArtifactPreview, listArtifacts, listEnterpriseProjects, listProjectEvidence, listProjectReportVersions } from '../../api/client';
import type { ArtifactPreview, ArtifactRecord, EvidenceRecord, ProjectRecord, ReportVersionRecord } from '../../api/types';
import { PixelIcon } from './PixelIcon';

type Folder = 'evidence' | 'reports' | 'attachments';
type FileSelection = { kind: 'evidence'; item: EvidenceRecord } | { kind: 'report'; item: ReportVersionRecord } | { kind: 'artifact'; item: ArtifactRecord } | null;

export function FilesApp() {
  const [projects, setProjects] = useState<ProjectRecord[]>([]);
  const [projectId, setProjectId] = useState('');
  const [folder, setFolder] = useState<Folder>('evidence');
  const [evidence, setEvidence] = useState<EvidenceRecord[]>([]);
  const [reports, setReports] = useState<ReportVersionRecord[]>([]);
  const [artifacts, setArtifacts] = useState<ArtifactRecord[]>([]);
  const [selected, setSelected] = useState<FileSelection>(null);
  const [preview, setPreview] = useState<ArtifactPreview | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    void listEnterpriseProjects().then(items => {
      if (!active) return;
      setProjects(items);
      setProjectId(id => id || items[0]?.id || '');
      if (!items.length) setLoading(false);
    }).catch(err => { if (active) { setError(err instanceof Error ? err.message : String(err)); setLoading(false); } });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    if (!projectId) return;
    let active = true;
    setLoading(true); setError(''); setSelected(null);
    void Promise.all([listProjectEvidence(projectId), listProjectReportVersions(projectId), listArtifacts({ projectId })])
      .then(([sources, versions, files]) => { if (active) { setEvidence(sources); setReports(versions); setArtifacts(files); } })
      .catch(err => { if (active) setError(err instanceof Error ? err.message : String(err)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [projectId]);
  useEffect(() => {
    if (selected?.kind !== 'artifact') { setPreview(null); return; }
    let active = true;
    setPreview(null);
    void getArtifactPreview(selected.item.id).then(value => { if (active) setPreview(value); }).catch(err => { if (active) setError(err instanceof Error ? err.message : String(err)); });
    return () => { active = false; };
  }, [selected]);
  function changeFolder(next: Folder) { setFolder(next); setSelected(null); setError(''); }
  return <section className="files-app">
    <header className="files-header"><span className="pixel-eyebrow">PROJECT FILES</span><h1>文件管理器</h1><p>项目里的证据、报告和附件，均来自现有工作区数据。</p></header>
    <div className="files-toolbar"><label>项目 <select value={projectId} onChange={e => setProjectId(e.target.value)} aria-label="选择项目">{projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label><span>{loading ? '读取中…' : `${folder === 'evidence' ? evidence.length : folder === 'reports' ? reports.length : artifacts.length} 个项目文件`}</span></div>
    {error && <p role="alert" className="files-error">{error}</p>}
    {!loading && !projects.length && !error && <p>暂无项目。<Link to="/">新建研究任务</Link>后会在这里看到文件。</p>}
    <div className="files-layout">
      <nav className="files-folders" aria-label="文件夹">
        <button type="button" data-action-id="files.folder.evidence" data-action-audit="local" className={folder === 'evidence' ? 'selected' : ''} onClick={() => changeFolder('evidence')}><PixelIcon name="folder" />证据 <span>{evidence.length}</span></button>
        <button type="button" data-action-id="files.folder.reports" data-action-audit="local" className={folder === 'reports' ? 'selected' : ''} onClick={() => changeFolder('reports')}><PixelIcon name="report" />报告 <span>{reports.length}</span></button>
        <button type="button" data-action-id="files.folder.attachments" data-action-audit="local" className={folder === 'attachments' ? 'selected' : ''} onClick={() => changeFolder('attachments')}><PixelIcon name="book" />附件 <span>{artifacts.length}</span></button>
      </nav>
      <div className="files-list" aria-label="项目文件">
        {folder === 'evidence' && evidence.map(item => <button type="button" data-action-id="files.evidence.select" data-action-audit="local" key={item.id} className={selected?.kind === 'evidence' && selected.item.id === item.id ? 'selected' : ''} onClick={() => setSelected({ kind: 'evidence', item })}><PixelIcon name="folder" /><span><strong>{item.title}</strong><small>{item.source_type} · {item.quality_label}</small></span></button>)}
        {folder === 'reports' && reports.map(item => <button type="button" data-action-id="files.report.select" data-action-audit="local" key={item.id} className={selected?.kind === 'report' && selected.item.id === item.id ? 'selected' : ''} onClick={() => setSelected({ kind: 'report', item })}><PixelIcon name="report" /><span><strong>版本 {item.version_number}</strong><small>{item.status} · {new Date(item.created_at).toLocaleDateString('zh-CN')}</small></span></button>)}
        {folder === 'attachments' && artifacts.map(item => <button type="button" data-action-id="files.artifact.select" data-action-audit="local" key={item.id} className={selected?.kind === 'artifact' && selected.item.id === item.id ? 'selected' : ''} onClick={() => setSelected({ kind: 'artifact', item })}><PixelIcon name="book" /><span><strong>{item.filename}</strong><small>{item.artifact_type} · {item.byte_size} B</small></span></button>)}
        {!loading && projectId && (folder === 'evidence' ? evidence : folder === 'reports' ? reports : artifacts).length === 0 && <p className="files-empty">这个文件夹还没有内容。</p>}
      </div>
      <article className="files-preview" aria-live="polite">
        {!selected && <p>选择文件查看内容和出处。</p>}
        {selected?.kind === 'evidence' && <><h2>{selected.item.title}</h2><p>{selected.item.snippet}</p><dl><dt>质量</dt><dd>{selected.item.quality_label}</dd><dt>来源类型</dt><dd>{selected.item.source_type}</dd><dt>采集时间</dt><dd>{selected.item.captured_at}</dd></dl>{selected.item.url && <a href={selected.item.url} target="_blank" rel="noreferrer">打开原始来源 ↗</a>}<p><Link to="/evidence">在证据中心查看 →</Link></p></>}
        {selected?.kind === 'report' && <><h2>报告版本 {selected.item.version_number}</h2><p>状态：{selected.item.status}</p><pre>{selected.item.full_report_md || selected.item.report_md || '这份报告暂无内容。'}</pre><Link to="/reports">前往报告审阅 →</Link></>}
        {selected?.kind === 'artifact' && <><h2>{selected.item.filename}</h2>{!preview && !error && <p>正在读取预览…</p>}{preview?.preview_type === 'text' && <pre>{preview.content_text}</pre>}{preview?.preview_type === 'image' && preview.data_url && <img src={preview.data_url} alt={selected.item.filename} />}{preview && !['text', 'image'].includes(preview.preview_type) && <p>此文件不能在窗口内预览。可在证据中心查看其记录。</p>}<Link to="/evidence">前往证据中心 →</Link></>}
      </article>
    </div>
  </section>;
}
