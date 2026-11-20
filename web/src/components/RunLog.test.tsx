// SPDX-License-Identifier: Apache-2.0
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../api";
import { RunLog } from "./RunLog";

vi.mock("../api", async (orig) => ({ ...(await orig<typeof import("../api")>()), getRunLog: vi.fn() }));
const getRunLog = vi.mocked(api.getRunLog);

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}
const line = (n: number, text: string) => ({ n, at: 1_700_000_000, line: text });

beforeEach(() => {
  vi.useFakeTimers();
  getRunLog.mockReset();
});
afterEach(() => vi.useRealTimers());

describe("RunLog", () => {
  it("pages incrementally with the last n", async () => {
    getRunLog.mockResolvedValueOnce({ lines: [line(3, "one"), line(5, "two")] });
    getRunLog.mockResolvedValue({ lines: [line(6, "three")] });
    render(<RunLog runId={4} running onClose={() => {}} />);
    await advance(0);
    expect(getRunLog).toHaveBeenLastCalledWith(4, 0);
    await advance(2000);
    expect(getRunLog).toHaveBeenLastCalledWith(4, 5);
    expect(screen.getByText(/one/)).toBeTruthy();
    expect(screen.getByText(/three/)).toBeTruthy();
  });

  it("stops polling when closed (unmounted)", async () => {
    getRunLog.mockResolvedValue({ lines: [] });
    const { unmount } = render(<RunLog runId={4} running onClose={() => {}} />);
    await advance(4000);
    const n = getRunLog.mock.calls.length;
    unmount();
    await advance(10_000);
    expect(getRunLog.mock.calls.length).toBe(n);
  });

  it("makes a final fetch when the run ends, then stops", async () => {
    getRunLog.mockResolvedValueOnce({ lines: [line(1, "a")] });
    getRunLog.mockResolvedValue({ lines: [line(2, "last line")] });
    const { rerender } = render(<RunLog runId={4} running onClose={() => {}} />);
    await advance(0);
    rerender(<RunLog runId={4} running={false} onClose={() => {}} />);
    await advance(0);
    expect(getRunLog).toHaveBeenLastCalledWith(4, 1);
    expect(screen.getByText(/last line/)).toBeTruthy();
    const n = getRunLog.mock.calls.length;
    await advance(10_000);
    expect(getRunLog.mock.calls.length).toBe(n);
  });
});
