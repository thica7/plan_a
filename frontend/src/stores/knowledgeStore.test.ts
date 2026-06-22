import { afterEach, describe, expect, it, vi } from "vitest";
import { useKnowledgeStore, type KnowledgeDocument } from "./knowledgeStore";

const emptyState = {
  documents: [],
  loading: false,
  error: null,
  filters: { competitor: "", dimension: "", source_type: "" },
  page: 1,
  pageSize: 10,
  totalCount: 0,
  debounceTimer: null,
  errorTimer: null,
  rollbackLoading: false,
  rollbackResult: null,
};

describe("useKnowledgeStore rollbackDocuments", () => {
  afterEach(() => {
    const { debounceTimer, errorTimer } = useKnowledgeStore.getState();
    if (debounceTimer) clearTimeout(debounceTimer);
    if (errorTimer) clearTimeout(errorTimer);
    useKnowledgeStore.setState(emptyState);
    vi.unstubAllGlobals();
  });

  it("posts compact rollback selectors and refreshes documents", async () => {
    const rollbackResult = {
      matched_count: 1,
      rolled_back_count: 1,
      restored_count: 1,
      archived_document_ids: ["doc-stale"],
      restored_document_ids: ["doc-previous"],
      skipped_document_ids: [],
      vector_cleanup_error: null,
    };
    const refreshedDocuments: KnowledgeDocument[] = [
      {
        id: "doc-previous",
        url: "https://example.com/pricing",
        title: "Example pricing",
        source_type: "webpage_verified",
        competitor: "Example",
        dimension: "pricing",
        content_hash: "hash-previous",
        text: "Restored pricing evidence.",
        markdown: "",
        status: "active",
        fetched_at: "2026-06-20T00:00:00.000Z",
        indexed_at: null,
        metadata: {},
      },
    ];

    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(rollbackResult))
      .mockResolvedValueOnce(jsonResponse(refreshedDocuments, { "X-Total-Count": "1" }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await useKnowledgeStore.getState().rollbackDocuments({
      run_id: "  run-1  ",
      raw_source_id: "",
      crawl_run_id: null,
      restore_previous: false,
    });

    expect(result).toEqual(rollbackResult);
    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/knowledge/documents/rollback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        document_ids: [],
        run_id: "run-1",
        raw_source_id: null,
        crawl_run_id: null,
        restore_previous: false,
      }),
    });
    expect(fetchMock).toHaveBeenNthCalledWith(2, "/api/knowledge/documents?page=1&page_size=10");
    expect(useKnowledgeStore.getState().rollbackResult).toEqual(rollbackResult);
    expect(useKnowledgeStore.getState().documents).toEqual(refreshedDocuments);
    expect(useKnowledgeStore.getState().totalCount).toBe(1);
  });

  it("rejects rollback without any selector before calling the API", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    await expect(useKnowledgeStore.getState().rollbackDocuments({ raw_source_id: " " })).rejects.toThrow(
      "At least one rollback selector is required",
    );

    expect(fetchMock).not.toHaveBeenCalled();
    expect(useKnowledgeStore.getState().rollbackLoading).toBe(false);
  });
});

function jsonResponse(body: unknown, headers: Record<string, string> = {}) {
  return {
    ok: true,
    status: 200,
    headers: new Headers(headers),
    json: async () => body,
  };
}
