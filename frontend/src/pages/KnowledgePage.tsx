import { useEffect, useRef, useState } from 'react';
import { useKnowledgeStore } from '../stores/knowledgeStore';
import { SourceCard } from '../components/SourceCard';
import { UploadDrawer } from '../features/upload/UploadDrawer';
import { VersionDrawer } from '../features/version/VersionDrawer';

type SortKey = 'fetched_at' | 'title' | 'source_type';
type DetailTab = 'content' | 'versions';

export default function KnowledgePage() {
  const {
    documents, loading, error, filters, page, pageSize, totalCount,
    fetchDocuments, deleteDocument, setFilter, setPage,
  } = useKnowledgeStore();

  const [sortBy, setSortBy] = useState<SortKey>('fetched_at');
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);
  const [detailTab, setDetailTab] = useState<DetailTab>('content');
  const [uploadOpen, setUploadOpen] = useState(false);
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

  const openDetail = (id: string) => {
    setSelectedDocId(id);
    setDetailTab('content');
    dialogRef.current?.showModal();
  };

  return (
    <div className="max-w-6xl mx-auto p-6 space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold">Knowledge Base</h1>
        <button type="button" className="btn btn-primary btn-sm" onClick={() => setUploadOpen(true)}>
          Bulk upload
        </button>
      </div>

      {/* Filters + Sort */}
      <div className="flex flex-wrap gap-4 items-center">
        <input
          className="input input-bordered w-48"
          placeholder="Competitor"
          value={filters.competitor}
          onChange={(e) => setFilter('competitor', e.target.value)}
        />
        <input
          className="input input-bordered w-48"
          placeholder="Dimension"
          value={filters.dimension}
          onChange={(e) => setFilter('dimension', e.target.value)}
        />
        <select
          className="select select-bordered w-48"
          value={filters.source_type}
          onChange={(e) => setFilter('source_type', e.target.value)}
        >
          <option value="">All sources</option>
          <option value="webpage_verified">Webpage (verified)</option>
          <option value="webpage_search">Webpage (search)</option>
          <option value="report">Report</option>
          <option value="manual">Manual</option>
        </select>
        <select
          className="select select-bordered w-40"
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value as SortKey)}
        >
          <option value="fetched_at">Date</option>
          <option value="title">Title</option>
          <option value="source_type">Source</option>
        </select>
      </div>

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
                  Delete
                </button>
              </div>
            ))}
            {sorted.length === 0 && (
              <p className="text-base-content/50 text-center py-12">No documents found.</p>
            )}
          </div>

          {/* Pagination */}
          {totalCount > pageSize && (
            <div className="flex justify-center">
              <div className="join">
                <button
                  className="join-item btn btn-sm"
                  disabled={page <= 1}
                  onClick={() => setPage(page - 1)}
                >
                  Prev
                </button>
                <button className="join-item btn btn-sm btn-disabled">
                  Page {page} of {totalPages}
                </button>
                <button
                  className="join-item btn btn-sm"
                  disabled={page >= totalPages}
                  onClick={() => setPage(page + 1)}
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </>
      )}

      {/* Document Detail Modal */}
      <dialog ref={dialogRef} className="modal">
        <div className="modal-box max-w-3xl max-h-[80vh]">
          {selectedDoc && (
            <>
              <h3 className="font-bold text-lg">{selectedDoc.title}</h3>
              <div className="flex flex-wrap gap-2 mt-2 text-xs">
                {selectedDoc.competitor && <span className="badge badge-sm">{selectedDoc.competitor}</span>}
                {selectedDoc.dimension && <span className="badge badge-sm badge-accent">{selectedDoc.dimension}</span>}
                <span className="badge badge-sm badge-ghost">{selectedDoc.source_type}</span>
                {selectedDoc.url && (
                  <a href={selectedDoc.url} target="_blank" rel="noopener noreferrer" className="link link-primary text-xs">
                    Open source
                  </a>
                )}
              </div>
              <div className="divider" />
              <div className="tabs tabs-boxed mb-3">
                <button
                  type="button"
                  className={`tab ${detailTab === 'content' ? 'tab-active' : ''}`}
                  onClick={() => setDetailTab('content')}
                >
                  Content
                </button>
                <button
                  type="button"
                  className={`tab ${detailTab === 'versions' ? 'tab-active' : ''}`}
                  onClick={() => setDetailTab('versions')}
                >
                  Versions
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
              <button className="btn">Close</button>
            </form>
          </div>
        </div>
        <form method="dialog" className="modal-backdrop">
          <button>close</button>
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
