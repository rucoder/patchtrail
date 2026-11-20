// SPDX-License-Identifier: Apache-2.0
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { run, status } from "../fixtures";
import * as api from "../api";
import { FetchButton } from "./FetchButton";


vi.mock("../api", async (orig) => ({ ...(await orig<typeof import("../api")>()), fetchNow: vi.fn(), getRunLog: vi.fn() }));
const fetchNow = vi.mocked(api.fetchNow);
const getRunLog = vi.mocked(api.getRunLog);

const NOW = 100_000;
beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW * 1000);
  fetchNow.mockReset();
  getRunLog.mockReset();
  getRunLog.mockResolvedValue({ lines: [] });
});
afterEach(() => vi.useRealTimers());

const noop = () => {};

describe("FetchButton", () => {
  it("renders a Fetch now button when idle", () => {
    render(<FetchButton status={status()} onStatus={noop} onRefresh={noop} />);
    expect(screen.getByRole("button", { name: "Fetch now" })).toBeTruthy();
  });

  it("renders the progress and no button while running", () => {
    const r = run({ id: 4, started_at: NOW - 65, phase: "fetching stable", step: 3, steps: 9 });
    render(<FetchButton status={status({ running: r })} onStatus={noop} onRefresh={noop} />);
    expect(screen.getByText("fetching stable · step 3 of 9 · 1m 05s")).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("shows starting… before the run row exists", () => {
    render(<FetchButton status={status({ starting: true })} onStatus={noop} onRefresh={noop} />);
    expect(screen.getByText("starting…")).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("sends one request on a double click", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    fetchNow.mockResolvedValue(status({ starting: true }));
    const onStatus = vi.fn();
    render(<FetchButton status={status()} onStatus={onStatus} onRefresh={noop} />);
    await user.dblClick(screen.getByRole("button", { name: "Fetch now" }));
    expect(fetchNow).toHaveBeenCalledTimes(1);
    expect(onStatus).toHaveBeenCalledWith(status({ starting: true }));
  });

  it("stays pending after a click until the next status arrives", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    fetchNow.mockResolvedValue(status());
    const { rerender } = render(<FetchButton status={status()} onStatus={noop} onRefresh={noop} />);
    await user.click(screen.getByRole("button", { name: "Fetch now" }));
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText("starting…")).toBeTruthy();
    rerender(<FetchButton status={status({ now: 2002 })} onStatus={noop} onRefresh={noop} />);
    expect(screen.getByRole("button", { name: "Fetch now" })).toBeTruthy();
  });

  it("shows the returned progress on a 409", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const r = run({ id: 9, started_at: NOW - 252, phase: "fetching lore", step: 1, steps: 4 });
    fetchNow.mockRejectedValue(new api.ApiError(409, "a fetch is running", { error: "x", running: r }));
    const onRefresh = vi.fn();
    render(<FetchButton status={status()} onStatus={noop} onRefresh={onRefresh} />);
    await user.click(screen.getByRole("button", { name: "Fetch now" }));
    expect(await screen.findByText("fetching lore · step 1 of 4 · 4m 12s")).toBeTruthy();
    expect(onRefresh).toHaveBeenCalled();
  });

  it("opens the run log when the progress is clicked", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    getRunLog.mockResolvedValue({ lines: [{ n: 1, at: NOW, line: "lore: 3 new mails" }] });
    const r = run({ id: 4, started_at: NOW - 5, phase: "p", step: 1, steps: 2 });
    render(<FetchButton status={status({ running: r })} onStatus={noop} onRefresh={noop} />);
    await user.click(screen.getByText(/step 1 of 2/));
    expect(await screen.findByText(/lore: 3 new mails/)).toBeTruthy();
    expect(getRunLog).toHaveBeenCalledWith(4, 0);
  });

  it("keeps the log after the run ends and does not open it for the next run", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    getRunLog.mockResolvedValue({ lines: [{ n: 1, at: NOW, line: "done soon" }] });
    const r4 = run({ id: 4, started_at: NOW - 5, phase: "p", step: 1, steps: 2 });
    const { rerender } = render(<FetchButton status={status({ running: r4 })} onStatus={noop} onRefresh={noop} />);
    await user.click(screen.getByText(/step 1 of 2/));
    expect(await screen.findByText(/done soon/)).toBeTruthy();
    rerender(<FetchButton status={status({ last_run: run({ id: 4, status: "ok", finished_at: NOW }) })}
      onStatus={noop} onRefresh={noop} />);
    expect(screen.getByRole("button", { name: "Fetch now" })).toBeTruthy();
    expect(screen.getByText(/done soon/)).toBeTruthy(); // still readable
    await user.click(screen.getByRole("button", { name: "close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    // a later run does not pop it open
    const r5 = run({ id: 5, started_at: NOW - 1, phase: "p", step: 1, steps: 2 });
    rerender(<FetchButton status={status({ running: r5 })} onStatus={noop} onRefresh={noop} />);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("closes a left-open log when a different run starts", async () => {
    const r4 = run({ id: 4, started_at: NOW - 5, phase: "p", step: 1, steps: 2 });
    const r5 = run({ id: 5, started_at: NOW - 1, phase: "p", step: 1, steps: 2 });
    const { rerender } = render(<FetchButton status={status({ running: r4 })} onStatus={noop} onRefresh={noop} />);
    await userEvent.click(screen.getByText(/step 1 of 2/));
    await screen.findByRole("dialog");
    rerender(<FetchButton status={status({ last_run: run({ id: 4, status: "ok" }) })} onStatus={noop} onRefresh={noop} />);
    rerender(<FetchButton status={status({ running: r5 })} onStatus={noop} onRefresh={noop} />);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("measures elapsed against the server clock", () => {
    const r = run({ started_at: NOW + 3600 - 65, phase: "p", step: 1, steps: 2 });
    render(<FetchButton status={status({ running: r })} onStatus={noop} onRefresh={noop} clockOffset={3600} />);
    expect(screen.getByText("p · step 1 of 2 · 1m 05s")).toBeTruthy();
  });
});
