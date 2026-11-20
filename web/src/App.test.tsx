// SPDX-License-Identifier: Apache-2.0
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "./api";
import { App } from "./App";
import { card, detail, run, status } from "./fixtures";
import type { Status } from "./types";

vi.mock("./api", async (orig) => ({
  ...(await orig<typeof import("./api")>()), getStatus: vi.fn(), getPatches: vi.fn(),
  fetchNow: vi.fn(), getRunLog: vi.fn(), act: vi.fn(), getPatch: vi.fn(),
}));
const getStatus = vi.mocked(api.getStatus);
const getPatches = vi.mocked(api.getPatches);

async function flush() {
  await act(async () => {});
}
async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  getStatus.mockReset();
  getPatches.mockReset();
  getStatus.mockResolvedValue(status());
  getPatches.mockResolvedValue({ patches: [card("a", { unread: true })] });
  history.replaceState(null, "", "/");
});
afterEach(() => vi.useRealTimers());

describe("App", () => {
  it("loads status and patches and shows the counts", async () => {
    render(<App />);
    await flush();
    expect(screen.getByText("Unread only · 1")).toBeTruthy();
    expect(getStatus).toHaveBeenCalledTimes(1);
  });

  it("polls the status every 30 s when idle", async () => {
    render(<App />);
    await flush();
    await advance(29_000);
    expect(getStatus).toHaveBeenCalledTimes(1);
    await advance(1_000);
    expect(getStatus).toHaveBeenCalledTimes(2);
    expect(getPatches).toHaveBeenCalledTimes(2); // the list also re-fetches every 30 s
  });

  it("polls the status every 2 s while a run is running", async () => {
    getStatus.mockResolvedValue(status({ running: run({ phase: "p", step: 1, steps: 2 }) }));
    render(<App />);
    await flush();
    const before = getStatus.mock.calls.length;
    await advance(6_000);
    expect(getStatus.mock.calls.length - before).toBe(3);
  });

  it("polls every 2 s while starting", async () => {
    getStatus.mockResolvedValue(status({ starting: true }));
    render(<App />);
    await flush();
    const before = getStatus.mock.calls.length;
    await advance(4_000);
    expect(getStatus.mock.calls.length - before).toBe(2);
  });

  it("re-fetches the patches when last_run.id changes", async () => {
    getStatus.mockResolvedValue(status({ running: run(), last_run: run({ id: 1, status: "ok", finished_at: 5 }) }));
    render(<App />);
    await flush();
    const before = getPatches.mock.calls.length;
    getStatus.mockResolvedValue(status({ last_run: run({ id: 2, status: "ok", finished_at: 9 }) }));
    await advance(2_000);
    expect(getPatches.mock.calls.length - before).toBe(1);
  });

  it("re-fetches the patches when a run ends that leaves last_run alone", async () => {
    // A lore-only run (Add thread, an agent's POST) is not a full run: last_run stays.
    const last = run({ id: 1, status: "ok", finished_at: 5 });
    getStatus.mockResolvedValue(status({ running: run({ id: 2, trigger: "api" }), last_run: last }));
    render(<App />);
    await flush();
    const before = getPatches.mock.calls.length;
    getStatus.mockResolvedValue(status({ last_run: last }));
    await advance(2_000);
    expect(getPatches.mock.calls.length - before).toBe(1);
  });

  it("reads the route from the URL and follows popstate", async () => {
    getPatches.mockResolvedValue({ patches: [card("iowq"), card("other")] });
    history.replaceState(null, "", "/p/iowq/thread");
    const { container } = render(<App />);
    await flush();
    expect(container.querySelector(".crd.sel .t")!.textContent).toBe("iowq");
    history.pushState(null, "", "/p/other");
    await act(async () => {
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    expect(container.querySelector(".crd.sel .t")!.textContent).toBe("other");
  });

  it("shows a connection error when the service is down and clears it on recovery", async () => {
    getStatus.mockRejectedValue(new Error("Failed to fetch"));
    getPatches.mockRejectedValue(new Error("Failed to fetch"));
    render(<App />);
    await flush();
    expect(screen.getByText(/cannot reach the service: Failed to fetch/).className).toContain("bad");
    getStatus.mockResolvedValue(status());
    getPatches.mockResolvedValue({ patches: [] });
    await advance(30_000);
    expect(screen.queryByText(/cannot reach the service/)).toBeNull();
  });

  it("shows a connection error when only the patches request fails", async () => {
    getPatches.mockRejectedValue(new Error("boom"));
    render(<App />);
    await flush();
    expect(screen.getByText(/cannot reach the service: boom/)).toBeTruthy();
  });

  it("applies only the newest status when replies arrive out of order", async () => {
    let resolveSlow!: (s: Status) => void;
    const slow = { promise: new Promise<Status>((r) => (resolveSlow = r)), resolve: (s: Status) => resolveSlow(s) };
    getStatus.mockReset();
    getStatus.mockReturnValueOnce(slow.promise);
    getStatus.mockResolvedValue(status({ error: { run_id: 1, at: 1_700_000_000, error: "fresh", status: "failed" } }));
    render(<App />);
    await advance(30_000); // a second, newer request answers first
    expect(screen.getByText(/fresh/)).toBeTruthy();
    await act(async () => slow.resolve(status({ error: { run_id: 1, at: 1_700_000_000, error: "stale", status: "failed" } })));
    expect(screen.queryByText(/stale/)).toBeNull();
    expect(screen.getByText(/fresh/)).toBeTruthy();
  });

  it("opens the panel on a deep link and reloads the detail when the card changes", async () => {
    history.replaceState(null, "", "/p/a/history");
    const getPatch = vi.mocked(api.getPatch);
    getPatch.mockReset();
    getPatch.mockResolvedValue(detail("a"));
    render(<App />);
    await flush();
    expect(getPatch).toHaveBeenCalledTimes(1);
    expect(screen.getByText("History").className).toContain("on");
    await advance(30_000); // same card JSON: no reload
    expect(getPatch).toHaveBeenCalledTimes(1);
    getPatches.mockResolvedValue({ patches: [card("a", { unread: true, unread_changes: 2 })] });
    await advance(30_000);
    expect(getPatch).toHaveBeenCalledTimes(2);
  });
});
