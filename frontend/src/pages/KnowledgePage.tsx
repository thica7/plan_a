import { FormEvent, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useKnowledgeStore, type KnowledgeChunk, type KnowledgeRollbackResult } from '../stores/knowledgeStore';
import { getArtifactPreview, listArtifacts } from '../api/client';
import type { ArtifactPreview, ArtifactRecord } from '../api/types';
import { SourceCard } from '../components/SourceCard';
import { UploadDrawer } from '../features/upload/UploadDrawer';
import { VersionDrawer } from '../features/version/VersionDrawer';
import { useTranslation } from '../stores/i18n';

type SortKey = 'fetched_at' | 'title' | 'source_type';
type DetailTab = 'content' | 'versions';

interface RollbackFormState {
  run_id: string;
  raw_source_id: string;
  crawl_run_id: string;
  restore_previous: boolean;
}

const EMPTY_ROLLBACK_FORM: RollbackFormState = {
  run_id: '',
  raw_source_id: '',
  crawl_run_id: '',
  restore_previous: true,
};

export default function KnowledgePage() {
  const { t } = useTranslation();
  const [searchParams] = useSearchParams();
  const focusDocumentId = searchParams.get('document_id')?.trim() || '';
  const focusChunkId = searchParams.get('chunk_id')?.trim() || '';
  const focusRawSourceId = searchParams.get('raw_source_id')?.trim() || '';
  const {
    documents, loading, error, filters, page, pageSize, totalCount,
    fetchDocuments, deleteDocument, rollbackDocuments, rollbackLoading, rollbackResult, setFilter, setPage,
  } = useKnowledgeStore();

  const [sortBy, setSortBy] = useState<SortKey>('fetched_at');
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);
  const [detailTab, setDetailTab] = useState<DetailTab>('content');
  const [uploadOpen, setUploadOpen] = useState(false);
  const [rollbackForm, setRollbackForm] = useState<RollbackFormState>(EMPTY_ROLLBACK_FORM);
  const [linkedDocument, setLinkedDocument] = useState<typeof documents[number] | null>(null);
  const [documentChunks, setDocumentChunks] = useState<KnowledgeChunk[]>([]);
  const [chunksLoading, setChunksLoading] = useState(false);
  const [sourceArtifacts, setSourceArtifacts] = useState<ArtifactRecord[]>([]);
  const [artifactPreview, setArtifactPreview] = useState<ArtifactPreview | null>(null);
  const [artifactLoading, setArtifactLoading] = useState(false);
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    fetchDocuments();
  }, [fetchDocuments]);

  useEffect(() => {
    if (!focusRawSourceId) return;
    setRollbackForm((current) => ({ ...current, raw_source_id: focusRawSourceId }));
  }, [focusRawSourceId]);

  useEffect(() => {
    if (!focusRawSourceId) {
      setSourceArtifacts([]);
      setArtifactPreview(null);
      return;
    }
    let active = true;
    setArtifactLoading(true);
    setSourceArtifacts([]);
    setArtifactPreview(null);
    listArtifacts({ rawSourceId: focusRawSourceId })
      .then((artifacts) => {
        if (!active) return null;
        const orderedArtifacts = prioritizeSourceSnapshotArtifacts(artifacts);
        setSourceArtifacts(orderedArtifacts);
        const primaryArtifact = orderedArtifacts[0];
        if (!primaryArtifact) return null;
        return getArtifactPreview(primaryArtifact.id).then((preview) => {
          if (active) setArtifactPreview(preview);
          return preview;
        });
      })
      .catch(() => {
        if (!active) return;
        setSourceArtifacts([]);
        setArtifactPreview(null);
      })
      .finally(() => {
        if (active) setArtifactLoading(false);
      });
    return () => {
      active = false;
    };
  }, [focusRawSourceId]);

  useEffect(() => {
    if (!focusDocumentId || documents.some((doc) => doc.id === focusDocumentId)) {
      setLinkedDocument(null);
      return;
    }
    let active = true;
    fetch(`/api/knowledge/documents/${encodeURIComponent(focusDocumentId)}`)
      .then((response) => (response.ok ? response.json() : null))
      .then((document) => {
        if (active) setLinkedDocument(document);
      })
      .catch(() => {
        if (active) setLinkedDocument(null);
      });
    return () => {
      active = false;
    };
  }, [documents, focusDocumentId]);

  const visibleDocuments =
    linkedDocument && !documents.some((doc) => doc.id === linkedDocument.id)
      ? [linkedDocument, ...documents]
      : documents;
  const sorted = [...visibleDocuments].sort((a, b) => {
    if (sortBy === 'title') return a.title.localeCompare(b.title);
    if (sortBy === 'source_type') return a.source_type.localeCompare(b.source_type);
    return new Date(b.fetched_at).getTime() - new Date(a.fetched_at).getTime();
  });

  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize));
  const selectedDoc = visibleDocuments.find((d) => d.id === selectedDocId) ?? null;
  const focusedDoc = focusDocumentId
    ? visibleDocuments.find((doc) => doc.id === focusDocumentId) ?? null
    : null;
  const canRollbackBySelector = Boolean(
    rollbackForm.run_id.trim() || rollbackForm.raw_source_id.trim() || rollbackForm.crawl_run_id.trim(),
  );

  const openDetail = (id: string) => {
    setSelectedDocId(id);
    setDetailTab('content');
    showDetailDialog(dialogRef.current);
  };

  useEffect(() => {
    if (!focusDocumentId || !focusedDoc) return;
    setSelectedDocId(focusDocumentId);
    setDetailTab('content');
    showDetailDialog(dialogRef.current);
  }, [focusedDoc, focusDocumentId]);

  useEffect(() => {
    if (!selectedDocId) {
      setDocumentChunks([]);
      return;
    }
    let active = true;
    setChunksLoading(true);
    fetch(`/api/knowledge/documents/${encodeURIComponent(selectedDocId)}/chunks`)
      .then((response) => (response.ok ? response.json() : []))
      .then((chunks) => {
        if (active) setDocumentChunks(Array.isArray(chunks) ? chunks : []);
      })
      .catch(() => {
        if (active) setDocumentChunks([]);
      })
      .finally(() => {
        if (active) setChunksLoading(false);
      });
    return () => {
      active = false;
    };
  }, [selectedDocId]);

  const updateRollbackField = (key: keyof RollbackFormState, value: string | boolean) => {
    setRollbackForm((current) => ({ ...current, [key]: value }));
  };

  const handleRollbackBySelector = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canRollbackBySelector) return;
    await rollbackDocuments(rollbackForm);
  };

  const handleRollbackDocument = async (documentId: string) => {
    await rollbackDocuments({
      document_ids: [documentId],
      restore_previous: rollbackForm.restore_previous,
    });
  };

  const focusedChunk = focusChunkId
    ? documentChunks.find((chunk) => chunk.id === focusChunkId) ?? null
    : null;

  return (
    <div className="max-w-6xl mx-auto p-6 space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold">{t('knowledge.title')}</h1>
        <button type="button" className="btn btn-primary btn-sm" onClick={() => setUploadOpen(true)}>
          {t('knowledge.bulkUpload')}
        </button>
      </div>

      <div className="flex flex-wrap gap-4 items-center">
        <input
          className="input input-bordered w-48"
          placeholder={t('knowledge.competitor')}
          value={filters.competitor}
          onChange={(e) => setFilter('competitor', e.target.value)}
        />
        <input
          className="input input-bordered w-48"
          placeholder={t('knowledge.dimension')}
          value={filters.dimension}
          onChange={(e) => setFilter('dimension', e.target.value)}
        />
        <select
          className="select select-bordered w-48"
          value={filters.source_type}
          onChange={(e) => setFilter('source_type', e.target.value)}
        >
          <option value="">{t('knowledge.allSources')}</option>
          <option value="webpage_verified">{t('knowledge.webpageVerified')}</option>
          <option value="webpage_search">{t('knowledge.webpageSearch')}</option>
          <option value="report">{t('knowledge.report')}</option>
          <option value="manual">{t('knowledge.manual')}</option>
        </select>
        <select
          className="select select-bordered w-40"
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value as SortKey)}
        >
          <option value="fetched_at">{t('knowledge.date')}</option>
          <option value="title">{t('knowledge.titleCol')}</option>
          <option value="source_type">{t('knowledge.source')}</option>
        </select>
      </div>

      <section className="rounded-lg border border-base-300 bg-base-100 p-4 shadow-sm">
        <form className="grid gap-3 md:grid-cols-[1fr_1fr_1fr_auto]" onSubmit={handleRollbackBySelector}>
          <label className="form-control">
            <span className="label-text">Run ID</span>
            <input
              className="input input-bordered input-sm"
              value={rollbackForm.run_id}
              onChange={(event) => updateRollbackField('run_id', event.target.value)}
            />
          </label>
          <label className="form-control">
            <span className="label-text">Raw source ID</span>
            <input
              className="input input-bordered input-sm"
              value={rollbackForm.raw_source_id}
              onChange={(event) => updateRollbackField('raw_source_id', event.target.value)}
            />
          </label>
          <label className="form-control">
            <span className="label-text">Crawl run ID</span>
            <input
              className="input input-bordered input-sm"
              value={rollbackForm.crawl_run_id}
              onChange={(event) => updateRollbackField('crawl_run_id', event.target.value)}
            />
          </label>
          <div className="flex flex-wrap items-end gap-3">
            <label className="label cursor-pointer gap-2 p-0 pb-1">
              <input
                checked={rollbackForm.restore_previous}
                className="checkbox checkbox-sm"
                type="checkbox"
                onChange={(event) => updateRollbackField('restore_previous', event.target.checked)}
              />
              <span className="label-text">Restore previous</span>
            </label>
            <button
              className="btn btn-warning btn-sm"
              disabled={!canRollbackBySelector || rollbackLoading}
              type="submit"
            >
              {rollbackLoading ? 'Rolling back...' : 'Rollback'}
            </button>
          </div>
        </form>
        {rollbackResult ? <RollbackResult result={rollbackResult} /> : null}
      </section>

      {error && <div className="alert alert-error">{error}</div>}

      {loading ? (
        <div className="flex justify-center py-12">
          <span className="loading loading-spinner loading-lg" />
        </div>
      ) : (
        <>
          <div className="grid gap-4">
            {sorted.map((doc) => (
              <div
                key={doc.id}
                className={`relative group ${documentMatchesLocator(doc, {
                  chunkId: focusChunkId,
                  documentId: focusDocumentId,
                  rawSourceId: focusRawSourceId,
                }) ? 'ring-2 ring-primary rounded-lg' : ''}`}
              >
                <div onClick={() => openDetail(doc.id)} className="cursor-pointer">
                  <SourceCard
                    title={doc.title}
                    url={doc.url}
                    competitor={doc.competitor}
                    dimension={doc.dimension}
                    source_type={doc.source_type}
                    fetched_at={doc.fetched_at}
                    snippet={doc.text.slice(0, 200)}
                  />
                </div>
                <button
                  className="btn btn-sm btn-error absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity"
                  onClick={() => deleteDocument(doc.id)}
                >
                  {t('common.delete')}
                </button>
              </div>
            ))}
            {sorted.length === 0 && (
              <p className="text-base-content/50 text-center py-12">{t('knowledge.noDocuments')}</p>
            )}
          </div>

          {totalCount > pageSize && (
            <div className="flex justify-center">
              <div className="join">
                <button
                  className="join-item btn btn-sm"
                  disabled={page <= 1}
                  onClick={() => setPage(page - 1)}
                >
                  {t('common.prev')}
                </button>
                <button className="join-item btn btn-sm btn-disabled">
                  {t('common.page')} {page} {t('common.of')} {totalPages}
                </button>
                <button
                  className="join-item btn btn-sm"
                  disabled={page >= totalPages}
                  onClick={() => setPage(page + 1)}
                >
                  {t('common.next')}
                </button>
              </div>
            </div>
          )}
        </>
      )}

      <dialog ref={dialogRef} className="modal">
        <div className="modal-box max-w-3xl max-h-[80vh]">
          {selectedDoc && (
            <>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h3 className="font-bold text-lg">{selectedDoc.title}</h3>
                  <div className="flex flex-wrap gap-2 mt-2 text-xs">
                    {selectedDoc.competitor && <span className="badge badge-sm">{selectedDoc.competitor}</span>}
                    {selectedDoc.dimension && <span className="badge badge-sm badge-accent">{selectedDoc.dimension}</span>}
                    <span className="badge badge-sm badge-ghost">{selectedDoc.source_type}</span>
                    {selectedDoc.url && (
                      <a href={selectedDoc.url} target="_blank" rel="noopener noreferrer" className="link link-primary text-xs">
                        {t('knowledge.openSource')}
                      </a>
                    )}
                  </div>
                </div>
                <button
                  className="btn btn-warning btn-sm"
                  disabled={rollbackLoading}
                  onClick={() => handleRollbackDocument(selectedDoc.id)}
                  type="button"
                >
                  {rollbackLoading ? 'Rolling back...' : 'Rollback document'}
                </button>
              </div>
              <div className="divider" />
              <div className="tabs tabs-boxed mb-3">
                <button
                  type="button"
                  className={`tab ${detailTab === 'content' ? 'tab-active' : ''}`}
                  onClick={() => setDetailTab('content')}
                >
                  {t('knowledge.content')}
                </button>
                <button
                  type="button"
                  className={`tab ${detailTab === 'versions' ? 'tab-active' : ''}`}
                  onClick={() => setDetailTab('versions')}
                >
                  {t('knowledge.versions')}
                </button>
              </div>
              {detailTab === 'content' ? (
                <>
                  {focusChunkId || focusRawSourceId ? (
                    <FocusedLocatorPanel
                      artifact={sourceArtifacts[0] ?? null}
                      artifactLoading={artifactLoading}
                      artifactPreview={artifactPreview}
                      chunkId={focusChunkId}
                      chunk={focusedChunk}
                      chunksLoading={chunksLoading}
                      rawSourceId={focusRawSourceId}
                    />
                  ) : null}
                  <div className="overflow-y-auto max-h-96 whitespace-pre-wrap text-sm">
                    {selectedDoc.markdown || selectedDoc.text}
                  </div>
                </>
              ) : (
                <VersionDrawer documentId={selectedDoc.id} onMerged={fetchDocuments} />
              )}
            </>
          )}
          <div className="modal-action">
            <form method="dialog">
              <button className="btn">{t('common.close')}</button>
            </form>
          </div>
        </div>
        <form method="dialog" className="modal-backdrop">
          <button>{t('common.close')}</button>
        </form>
      </dialog>

      <UploadDrawer
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        onComplete={fetchDocuments}
      />
    </div>
  );
}

function FocusedLocatorPanel({
  artifact,
  artifactLoading,
  artifactPreview,
  chunk,
  chunkId,
  chunksLoading,
  rawSourceId,
}: {
  artifact: ArtifactRecord | null;
  artifactLoading: boolean;
  artifactPreview: ArtifactPreview | null;
  chunk: KnowledgeChunk | null;
  chunkId: string;
  chunksLoading: boolean;
  rawSourceId: string;
}) {
  return (
    <section className="mb-4 rounded-lg border border-primary/30 bg-primary/5 p-3 text-sm" aria-label="Focused KB locator">
      <div className="mb-2 flex flex-wrap gap-2">
        {chunkId ? <span className="badge badge-primary badge-outline">chunk {chunkId}</span> : null}
        {rawSourceId ? <span className="badge badge-ghost">raw source {rawSourceId}</span> : null}
      </div>
      {chunkId ? (
        chunksLoading ? (
          <p className="text-base-content/60">Loading focused chunk...</p>
        ) : chunk ? (
          <pre className="max-h-48 overflow-y-auto whitespace-pre-wrap rounded bg-base-100 p-3 text-xs">
            {chunk.text}
          </pre>
        ) : (
          <p className="text-base-content/60">Focused chunk was not found in this document.</p>
        )
      ) : (
        <p className="text-base-content/60">Use the raw source selector above to rollback or inspect related evidence.</p>
      )}
      {rawSourceId ? (
        <div className="mt-3 border-t border-primary/20 pt-3">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <span className="font-medium">Source snapshot</span>
            {artifact ? <span className="badge badge-outline badge-sm">{artifact.artifact_type}</span> : null}
            {artifact ? <span className="badge badge-ghost badge-sm">{artifact.filename}</span> : null}
          </div>
          {artifactLoading ? (
            <p className="text-base-content/60">Loading source snapshot...</p>
          ) : artifactPreview?.preview_available && artifactPreview.preview_type === 'image' && artifactPreview.data_url ? (
            <img
              alt={`Source snapshot ${artifactPreview.artifact.filename}`}
              className="max-h-64 w-full rounded bg-base-100 object-contain"
              src={artifactPreview.data_url}
            />
          ) : artifactPreview?.preview_available && artifactPreview.preview_type === 'pdf' && artifactPreview.data_url ? (
            <iframe
              className="h-64 w-full rounded bg-base-100"
              src={artifactPreview.data_url}
              title={`Source snapshot ${artifactPreview.artifact.filename}`}
            />
          ) : artifactPreview?.preview_available && artifactPreview.preview_type === 'text' ? (
            <>
              <pre className="max-h-48 overflow-y-auto whitespace-pre-wrap rounded bg-base-100 p-3 text-xs">
                {artifactPreview.content_text}
              </pre>
              {artifactPreview.truncated ? (
                <p className="mt-2 text-xs text-base-content/60">Preview truncated.</p>
              ) : null}
            </>
          ) : artifactPreview?.truncated ? (
            <p className="text-base-content/60">Source snapshot is too large for inline preview.</p>
          ) : artifactPreview?.external_uri ? (
            <code className="block overflow-x-auto rounded bg-base-100 p-2 text-xs">
              {artifactPreview.external_uri}
            </code>
          ) : artifact ? (
            <p className="text-base-content/60">No readable local preview is available for this artifact.</p>
          ) : (
            <p className="text-base-content/60">No source snapshot artifact is linked to this raw source.</p>
          )}
        </div>
      ) : null}
    </section>
  );
}

function prioritizeSourceSnapshotArtifacts(artifacts: ArtifactRecord[]) {
  return [...artifacts].sort((left, right) => {
    const leftRank = sourceSnapshotArtifactRank(left);
    const rightRank = sourceSnapshotArtifactRank(right);
    if (leftRank !== rightRank) return leftRank - rightRank;
    return new Date(right.created_at).getTime() - new Date(left.created_at).getTime();
  });
}

function sourceSnapshotArtifactRank(artifact: ArtifactRecord) {
  if (metadataText(artifact.metadata, 'snapshot_kind')) return 0;
  if (
    [
      'web_snapshot',
      'pdf',
      'screenshot',
      'raw_text',
      'interview_record',
      'survey_response',
      'manual_transcript',
    ].includes(artifact.artifact_type)
  ) {
    return 1;
  }
  return 2;
}

function showDetailDialog(dialog: HTMLDialogElement | null) {
  if (!dialog || dialog.open || typeof dialog.showModal !== 'function') return;
  dialog.showModal();
}

function documentMatchesLocator(
  document: {
    id: string;
    metadata: Record<string, unknown>;
  },
  locator: {
    chunkId: string;
    documentId: string;
    rawSourceId: string;
  },
) {
  if (locator.documentId && document.id === locator.documentId) return true;
  if (locator.rawSourceId && metadataText(document.metadata, 'raw_source_id') === locator.rawSourceId) return true;
  if (locator.rawSourceId && metadataText(document.metadata, 'kb_raw_source_id') === locator.rawSourceId) return true;
  if (locator.chunkId && metadataStringList(document.metadata, 'chunk_ids').includes(locator.chunkId)) return true;
  if (locator.chunkId && metadataStringList(document.metadata, 'kb_chunk_ids').includes(locator.chunkId)) return true;
  return false;
}

function metadataText(metadata: Record<string, unknown>, key: string) {
  const value = metadata[key];
  if (value === null || value === undefined || value === '') return '';
  return String(value);
}

function metadataStringList(metadata: Record<string, unknown>, key: string) {
  const value = metadata[key];
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item || '').trim()).filter(Boolean);
}

function RollbackResult({ result }: { result: KnowledgeRollbackResult }) {
  return (
    <div className="mt-3 grid gap-2 text-sm">
      <div className="flex flex-wrap gap-2">
        <span className="badge badge-outline">Matched {result.matched_count}</span>
        <span className="badge badge-warning">Archived {result.rolled_back_count}</span>
        <span className="badge badge-success">Restored {result.restored_count}</span>
        {result.skipped_document_ids.length > 0 ? (
          <span className="badge badge-ghost">Skipped {result.skipped_document_ids.length}</span>
        ) : null}
      </div>
      {result.archived_document_ids.length > 0 ? (
        <code>archived: {result.archived_document_ids.join(', ')}</code>
      ) : null}
      {result.restored_document_ids.length > 0 ? (
        <code>restored: {result.restored_document_ids.join(', ')}</code>
      ) : null}
      {result.vector_cleanup_error ? (
        <div className="alert alert-warning py-2">vector cleanup: {result.vector_cleanup_error}</div>
      ) : null}
    </div>
  );
}
