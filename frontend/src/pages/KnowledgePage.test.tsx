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
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/knowledge/documents?page=1&page_size=10") {
        return Promise.resolve(jsonResponse([linkedDocument], { "X-Total-Count": "1" }));
      }
      if (url === "/api/knowledge/documents/kb-doc-security-v2") {
        return Promise.resolve(jsonResponse(linkedDocument));
      }
      if (url === "/api/knowledge/documents/kb-doc-security-v2/chunks") {
        return Promise.resolve(
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
      }
      if (url === "/api/enterprise/artifacts?raw_source_id=kb-security-sso") {
        return Promise.resolve(
          jsonResponse([
            {
              id: "artifact-security-snapshot",
              workspace_id: "workspace-a",
              project_id: "project-a",
              evidence_id: "evidence-security",
              run_id: "run-security",
              report_version_id: "report-v1",
              artifact_type: "web_snapshot",
              filename: "security-snapshot.html",
              media_type: "text/html",
              storage_backend: "local",
              uri: "local://workspace-a/artifact-security-snapshot/security-snapshot.html",
              byte_size: 120,
              content_hash: "artifact-hash",
              source_url: "https://acme.example/security",
              created_by: "collector",
              created_at: "2026-06-20T00:01:00.000Z",
              retention_policy: "90d",
              compliance_metadata: {},
              metadata: {
                raw_source_id: "kb-security-sso",
                snapshot_kind: "webpage",
              },
            },
          ]),
        );
      }
      if (url === "/api/enterprise/artifacts/artifact-security-snapshot/preview") {
        return Promise.resolve(
          jsonResponse({
            artifact: {
              id: "artifact-security-snapshot",
              workspace_id: "workspace-a",
              project_id: "project-a",
              artifact_type: "web_snapshot",
              filename: "security-snapshot.html",
              media_type: "text/html",
              storage_backend: "local",
              uri: "local://workspace-a/artifact-security-snapshot/security-snapshot.html",
              byte_size: 120,
              content_hash: "artifact-hash",
              source_url: "https://acme.example/security",
              created_by: "collector",
              created_at: "2026-06-20T00:01:00.000Z",
              metadata: {},
            },
            preview_available: true,
            content_text: "<html>Source snapshot: Acme security page captured SSO support.</html>",
            truncated: false,
            external_uri: null,
          }),
        );
      }
      return Promise.resolve(jsonResponse(null));
    });
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
    expect(await screen.findByText(/Source snapshot: Acme security page/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("Raw source ID")).toHaveValue("kb-security-sso"));
    expect(fetchMock).toHaveBeenCalledWith("/api/knowledge/documents?page=1&page_size=10");
    expect(fetchMock).toHaveBeenCalledWith("/api/knowledge/documents/kb-doc-security-v2");
    expect(fetchMock).toHaveBeenCalledWith("/api/knowledge/documents/kb-doc-security-v2/chunks");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/enterprise/artifacts?raw_source_id=kb-security-sso",
      expect.any(Object),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/enterprise/artifacts/artifact-security-snapshot/preview",
      expect.any(Object),
    );
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
