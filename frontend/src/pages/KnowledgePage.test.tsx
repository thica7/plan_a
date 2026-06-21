import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import KnowledgePage from "./KnowledgePage";
import { useKnowledgeStore, type KnowledgeDocument } from "../stores/knowledgeStore";

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

const linkedDocument: KnowledgeDocument = {
  id: "kb-doc-security-v2",
  url: "https://acme.example/security",
  title: "Acme security docs",
  source_type: "webpage_verified",
  competitor: "Acme",
  dimension: "security",
  content_hash: "hash-security",
  text: "Acme supports SSO in the active security docs.",
  markdown: "",
  status: "active",
  fetched_at: "2026-06-20T00:00:00.000Z",
  indexed_at: null,
  metadata: {
    chunk_ids: ["kb-chunk-security-4"],
    raw_source_id: "kb-security-sso",
  },
};

describe("KnowledgePage deep links", () => {
  afterEach(() => {
    const { debounceTimer, errorTimer } = useKnowledgeStore.getState();
    if (debounceTimer) clearTimeout(debounceTimer);
    if (errorTimer) clearTimeout(errorTimer);
    useKnowledgeStore.setState(emptyState);
    vi.unstubAllGlobals();
  });

  it("focuses a KB locator from query params", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse([linkedDocument], { "X-Total-Count": "1" }))
      .mockResolvedValueOnce(jsonResponse(linkedDocument))
      .mockResolvedValueOnce(
        jsonResponse([
          {
            id: "kb-chunk-security-4",
            document_id: "kb-doc-security-v2",
            chunk_index: 4,
            text: "Focused chunk: Acme supports SSO in the active security docs.",
            token_count: 10,
            embedding_model: "hash",
            content_hash: "hash-chunk",
            crawl_run_id: null,
            metadata: {},
          },
        ]),
      );
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MemoryRouter
        initialEntries={[
          "/knowledge?document_id=kb-doc-security-v2&chunk_id=kb-chunk-security-4&raw_source_id=kb-security-sso",
        ]}
      >
        <KnowledgePage />
      </MemoryRouter>,
    );

    expect(await screen.findAllByText("Acme security docs")).not.toHaveLength(0);
    expect(await screen.findByText(/Focused chunk: Acme supports SSO/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("Raw source ID")).toHaveValue("kb-security-sso"));
    expect(fetchMock).toHaveBeenCalledWith("/api/knowledge/documents?page=1&page_size=10");
    expect(fetchMock).toHaveBeenCalledWith("/api/knowledge/documents/kb-doc-security-v2");
    expect(fetchMock).toHaveBeenCalledWith("/api/knowledge/documents/kb-doc-security-v2/chunks");
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
