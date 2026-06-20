import { FormEvent, useEffect, useRef, useState } from 'react';
import { useKnowledgeStore, type KnowledgeRollbackResult } from '../stores/knowledgeStore';
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
  const {
    documents, loading, error, filters, page, pageSize, totalCount,
    fetchDocuments, deleteDocument, rollbackDocuments, rollbackLoading, rollbackResult, setFilter, setPage,
  } = useKnowledgeStore();

  const [sortBy, setSortBy] = useState<SortKey>('fetched_at');
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);
  const [detailTab, setDetailTab] = useState<DetailTab>('content');
  const [uploadOpen, setUploadOpen] = useState(false);
  const [rollbackForm, setRollbackForm] = useState<RollbackFormState>(EMPTY_ROLLBACK_FORM);
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    fetchDocuments();
  }, [fetchDocuments]);

  const sorted = [...documents].sort((a, b) => {
    if (sortBy === 'title') return a.title.localeCompare(b.title);
    if (sortBy === 'source_type') return a.source_type.localeCompare(b.source_type);
    return new Date(b.fetched_at).getTime() - new Date(a.fetched_at).getTime();
  });

  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize));
  const selectedDoc = documents.find((d) => d.id === selectedDocId) ?? null;
  const canRollbackBySelector = Boolean(
    rollbackForm.run_id.trim() || rollbackForm.raw_source_id.trim() || rollbackForm.crawl_run_id.trim(),
  );

  const openDetail = (id: string) => {
    setSelectedDocId(id);
    setDetailTab('content');
    dialogRef.current?.showModal();
  };

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
              <div key={doc.id} className="relative group">
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
                <div className="overflow-y-auto max-h-96 whitespace-pre-wrap text-sm">
                  {selectedDoc.markdown || selectedDoc.text}
                </div>
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
