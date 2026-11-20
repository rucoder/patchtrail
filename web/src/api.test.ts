// SPDX-License-Identifier: Apache-2.0
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, addPatch, ApiError, fetchNow, getRunLog, getStatus } from "./api";

function reply(status: number, body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status }));
}

let f: ReturnType<typeof vi.fn>;
beforeEach(() => {
  f = vi.fn();
  vi.stubGlobal("fetch", f);
});
afterEach(() => vi.unstubAllGlobals());

describe("api", () => {
  it("reads without a content type", async () => {
    f.mockReturnValue(reply(200, { version: "1" }));
    await getStatus();
    expect(f.mock.calls[0][0]).toBe("/api/status");
    expect(new Headers(f.mock.calls[0][1]?.headers).get("Content-Type")).toBeNull();
  });
  it("sends JSON content type on writes", async () => {
    f.mockReturnValue(reply(202, {}));
    await fetchNow();
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("/api/fetch");
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("Content-Type")).toBe("application/json");
    expect(init.body).toBe("{}");
  });
  it("addPatch and act use the right verbs and paths", async () => {
    f.mockReturnValue(reply(200, {}));
    await addPatch({ name: "x", msgid: "m" });
    expect(f.mock.calls[0][0]).toBe("/api/patches");
    await act("a b", "read");
    expect(f.mock.calls[1][0]).toBe("/api/patches/a%20b/read");
    expect(f.mock.calls[1][1].body).toBe("{}");
    await act("a", "setNote", { note: "hi" });
    expect(f.mock.calls[2][0]).toBe("/api/patches/a/note");
    expect(f.mock.calls[2][1].method).toBe("PUT");
    expect(JSON.parse(f.mock.calls[2][1].body)).toEqual({ note: "hi" });
  });
  it("passes after on the run log", async () => {
    f.mockReturnValue(reply(200, { lines: [] }));
    await getRunLog(7, 12);
    expect(f.mock.calls[0][0]).toBe("/api/runs/7/log?after=12");
  });
  it("throws ApiError carrying status, message and body on 409", async () => {
    const body = { error: "busy", running: { id: 3 } };
    f.mockReturnValue(reply(409, body));
    const err = await fetchNow().catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(409);
    expect(err.message).toBe("busy");
    expect(err.body).toEqual(body);
  });
  it("throws ApiError on a non-JSON error body", async () => {
    f.mockReturnValue(Promise.resolve(new Response("oops", { status: 502 })));
    const err = await getStatus().catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(502);
  });
});
