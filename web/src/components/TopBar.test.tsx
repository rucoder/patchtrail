// SPDX-License-Identifier: Apache-2.0
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { card, run, status } from "../fixtures";
import { defaultFilters } from "../lib/filters";
import { clock, dayTime } from "../lib/time";
import { TopBar } from "./TopBar";

const noop = () => {};
function bar(over: Partial<Parameters<typeof TopBar>[0]> = {}) {
  return render(
    <TopBar status={status()} patches={[]} filters={defaultFilters} onFilters={noop}
      onStatus={noop} onRefresh={noop} onAdded={noop} {...over} />,
  );
}

const patches = [
  card("a", { unread: true, your_turn: true }),
  card("b", { unread: true, project: "QEMU" }),
  card("c", { your_turn: true, project: "QEMU" }),
  card("d", { unread: true, hidden: true }),
  card("e", { unread: true, closed: "rejected" }),
];

describe("TopBar", () => {
  it("shows the counts over the open cards", () => {
    bar({ patches });
    expect(screen.getByText("Unread only · 2")).toBeTruthy();
    expect(screen.getByText("Your turn · 2")).toBeTruthy();
  });

  it("counts within the project filter and the view", () => {
    bar({ patches, filters: { ...defaultFilters, project: "QEMU" } });
    expect(screen.getByText("Unread only · 1")).toBeTruthy();
    expect(screen.getByText("Your turn · 1")).toBeTruthy();
  });

  it("offers All plus each project present, and reports clicks", async () => {
    const onFilters = vi.fn();
    bar({ patches, onFilters });
    expect(screen.getByRole("button", { name: "All" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "kernel" })).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "QEMU" }));
    expect(onFilters).toHaveBeenCalledWith({ ...defaultFilters, project: "QEMU" });
    await userEvent.click(screen.getByText("Unread only · 2"));
    expect(onFilters).toHaveBeenLastCalledWith({ ...defaultFilters, unread: true });
  });

  it("changes the view with the select", async () => {
    const onFilters = vi.fn();
    bar({ onFilters });
    await userEvent.selectOptions(screen.getByRole("combobox"), "closed");
    expect(onFilters).toHaveBeenCalledWith({ ...defaultFilters, view: "closed" });
  });

  it("shows fetched and next times", () => {
    const fin = 1_700_000_000;
    bar({ status: status({ last_run: run({ status: "ok", finished_at: fin }), next_fetch_at: fin + 10800 }) });
    expect(screen.getByText(`fetched ${clock(fin)} · next ${clock(fin + 10800)}`)).toBeTruthy();
  });

  it("says a fetch was interrupted, and why", () => {
    const err = { run_id: 4, at: 1_700_000_000, error: "killed after 4 hours", status: "interrupted" as const };
    bar({ status: status({ error: err, last_run: run({ id: 2, status: "ok", finished_at: 1_699_990_000 }) }) });
    const el = screen.getByText(/last fetch interrupted/);
    expect(el.className).toContain("bad");
    expect(el.textContent).toContain(`${dayTime(err.at)}: killed after 4 hours`);
    expect(screen.getByText(new RegExp(`fetched ${clock(1_699_990_000)}`))).toBeTruthy();
  });

  it("shows the error banner while status.error is set, not after", () => {
    const err = { run_id: 3, at: 1_700_000_000, error: "b4 exploded", status: "failed" as const };
    const { rerender } = bar({ status: status({ error: err }) });
    const el = screen.getByText(/b4 exploded/);
    expect(el.className).toContain("bad");
    expect(el.textContent).toBe(`last fetch failed ${dayTime(err.at)}: b4 exploded`);
    rerender(
      <TopBar status={status()} patches={[]} filters={defaultFilters} onFilters={noop}
        onStatus={noop} onRefresh={noop} onAdded={noop} />,
    );
    expect(screen.queryByText(/b4 exploded/)).toBeNull();
  });

  it("opens the Add thread dialog", async () => {
    bar();
    await userEvent.click(screen.getByRole("button", { name: "Add thread" }));
    expect(screen.getByRole("dialog")).toBeTruthy();
  });
});
