import { afterEach, describe, expect, it, vi } from "vitest";
import { createRun } from "./client";

describe("api client auth headers", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.localStorage.clear();
  });

  it("sends configured bearer and user identity headers with requests", async () => {
    window.localStorage.setItem("competiscope.authToken", "local-token");
    window.localStorage.setItem("competiscope.userId", "user-a");
    window.localStorage.setItem("competiscope.userRole", "analyst");
    window.localStorage.setItem("competiscope.workspaceId", "workspace-a");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: "run-1" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await createRun({ idempotency_key: "key-1" } as Parameters<typeof createRun>[0]);

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(init.headers).toEqual(
      expect.objectContaining({
        "Content-Type": "application/json",
        Authorization: "Bearer local-token",
        "X-User-Id": "user-a",
        "X-User-Role": "analyst",
        "X-Workspace-Id": "workspace-a",
      }),
    );
  });
});
