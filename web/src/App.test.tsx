// SPDX-License-Identifier: Apache-2.0
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "./api";
import { App } from "./App";
import { card, run, status } from "./fixtures";

vi.mock("./api", async (orig) => ({
  ...(await orig<typeof import("./api")>()), getStatus: vi.fn(), getPatches: vi.fn(),
  fetchNow: vi.fn(), getRunLog: vi.fn(), act: vi.fn(),
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

  it("reads the route from the URL and follows popstate", async () => {
    history.replaceState(null, "", "/p/iowq/thread");
    render(<App />);
    await flush();
    expect(screen.getByText(/selected: iowq/)).toBeTruthy();
    history.pushState(null, "", "/p/other");
    await act(async () => {
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    expect(screen.getByText(/selected: other/)).toBeTruthy();
  });
});
