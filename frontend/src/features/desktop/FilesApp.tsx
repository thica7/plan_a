import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getArtifactPreview, listArtifacts, listEnterpriseProjects, listProjectEvidence, listProjectReportVersions } from '../../api/client';
import type { ArtifactPreview, ArtifactRecord, EvidenceRecord, ProjectRecord, ReportVersionRecord } from '../../api/types';
import { PixelIcon } from './PixelIcon';
import { useTranslation } from '../../stores/i18n';
import { displayLabel } from '../../i18n/display';
import { SystemMessage } from '../../i18n/SystemMessage';

type Folder = 'evidence' | 'reports' | 'attachments';
type FileSelection = { kind: 'evidence'; item: EvidenceRecord } | { kind: 'report'; item: ReportVersionRecord } | { kind: 'artifact'; item: ArtifactRecord } | null;

export function FilesApp() {
  const { t, locale } = useTranslation();
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
    <header className="files-header"><span className="pixel-eyebrow">{t('files.eyebrow')}</span><h1>{t('files.title')}</h1><p>{t('files.description')}</p></header>
    <div className="files-toolbar"><label>{t('files.project')} <select value={projectId} onChange={e => setProjectId(e.target.value)} aria-label={t('files.selectProject')}>{projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label><span>{loading ? t('files.loading') : `${folder === 'evidence' ? evidence.length : folder === 'reports' ? reports.length : artifacts.length} ${t('files.count')}`}</span></div>
    {error && <p role="alert" className="files-error"><SystemMessage message={error} /></p>}
    {!loading && !projects.length && !error && <p>{t('files.noProjects')}<Link to="/">{t('files.newResearch')}</Link>{t('files.afterResearch')}</p>}
    <div className="files-layout">
      <nav className="files-folders" aria-label={t('files.folders')}>
        <button type="button" data-action-id="files.folder.evidence" data-action-audit="local" className={folder === 'evidence' ? 'selected' : ''} onClick={() => changeFolder('evidence')}><PixelIcon name="folder" />{t('files.evidence')} <span>{evidence.length}</span></button>
        <button type="button" data-action-id="files.folder.reports" data-action-audit="local" className={folder === 'reports' ? 'selected' : ''} onClick={() => changeFolder('reports')}><PixelIcon name="report" />{t('files.reports')} <span>{reports.length}</span></button>
        <button type="button" data-action-id="files.folder.attachments" data-action-audit="local" className={folder === 'attachments' ? 'selected' : ''} onClick={() => changeFolder('attachments')}><PixelIcon name="book" />{t('files.attachments')} <span>{artifacts.length}</span></button>
      </nav>
      <div className="files-list" aria-label={t('files.eyebrow')}>
        {folder === 'evidence' && evidence.map(item => <button type="button" data-action-id="files.evidence.select" data-action-audit="local" key={item.id} className={selected?.kind === 'evidence' && selected.item.id === item.id ? 'selected' : ''} onClick={() => setSelected({ kind: 'evidence', item })}><PixelIcon name="folder" /><span><strong>{item.title}</strong><small>{displayLabel(item.source_type, locale)} · {displayLabel(item.quality_label, locale)}</small></span></button>)}
        {folder === 'reports' && reports.map(item => <button type="button" data-action-id="files.report.select" data-action-audit="local" key={item.id} className={selected?.kind === 'report' && selected.item.id === item.id ? 'selected' : ''} onClick={() => setSelected({ kind: 'report', item })}><PixelIcon name="report" /><span><strong>{t('version.version')} {item.version_number}</strong><small>{displayLabel(item.status, locale)} · {new Date(item.created_at).toLocaleDateString(locale)}</small></span></button>)}
        {folder === 'attachments' && artifacts.map(item => <button type="button" data-action-id="files.artifact.select" data-action-audit="local" key={item.id} className={selected?.kind === 'artifact' && selected.item.id === item.id ? 'selected' : ''} onClick={() => setSelected({ kind: 'artifact', item })}><PixelIcon name="book" /><span><strong>{item.filename}</strong><small>{displayLabel(item.artifact_type, locale)} · {item.byte_size} {t('common.bytes')}</small></span></button>)}
        {!loading && projectId && (folder === 'evidence' ? evidence : folder === 'reports' ? reports : artifacts).length === 0 && <p className="files-empty">{t('files.emptyFolder')}</p>}
      </div>
      <article className="files-preview" aria-live="polite">
        {!selected && <p>{t('files.chooseFile')}</p>}
        {selected?.kind === 'evidence' && <><h2>{selected.item.title}</h2><p>{selected.item.snippet}</p><dl><dt>{t('files.quality')}</dt><dd>{displayLabel(selected.item.quality_label, locale)}</dd><dt>{t('files.sourceType')}</dt><dd>{displayLabel(selected.item.source_type, locale)}</dd><dt>{t('files.capturedAt')}</dt><dd>{selected.item.captured_at}</dd></dl>{selected.item.url && <a href={selected.item.url} target="_blank" rel="noreferrer">{t('files.openSource')} ↗</a>}<p><Link to="/evidence">{t('files.openEvidence')} →</Link></p></>}
        {selected?.kind === 'report' && <><h2>{t('workbench.reportVersion')} {selected.item.version_number}</h2><p>{t('compliance.status')}：{displayLabel(selected.item.status, locale)}</p><pre>{selected.item.full_report_md || selected.item.report_md || t('files.emptyReport')}</pre><Link to="/reports">{t('files.openReports')} →</Link></>}
        {selected?.kind === 'artifact' && <><h2>{selected.item.filename}</h2>{!preview && !error && <p>{t('files.loadingPreview')}</p>}{preview?.preview_type === 'text' && <pre>{preview.content_text}</pre>}{preview?.preview_type === 'image' && preview.data_url && <img src={preview.data_url} alt={selected.item.filename} />}{preview && !['text', 'image'].includes(preview.preview_type) && <p>{t('files.unsupportedPreview')}</p>}<Link to="/evidence">{t('files.openEvidence')} →</Link></>}
      </article>
    </div>
  </section>;
}
