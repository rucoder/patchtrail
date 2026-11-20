// SPDX-License-Identifier: Apache-2.0
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { detail } from "../fixtures";
import type { BranchRow, Detail, Prereq } from "../types";
import { Overview } from "./Overview";

const act = vi.fn(async () => true);
function show(d: Detail) {
  act.mockClear();
  return render(<Overview d={d} card={d} act={act} />);
}
const row = (over: Partial<BranchRow> = {}): BranchRow => ({
  sha: "aaaaaaaaaaaa", state: "applies", tag: null, tone: "ok", detail: ["cleanly"], prereqs: [], ...over,
});

describe("Overview", () => {
  it("marks done and skipped steps in the stepper", () => {
    const { container } = show(detail("p", { steps: [
      { stage: "submitted", state: "done", at: 1_700_000_000, note: null },
      { stage: "reviewed", state: "skipped", at: null, note: null },
      { stage: "accepted", state: "todo", at: null, note: "io_uring-7.4" },
    ] }));
    const steps = container.querySelectorAll(".trail .step");
    expect(steps[0].className).toContain("d");
    expect(steps[1].className).toContain("skip");
    expect(steps[2].className).toBe("step");
    expect(steps[2].textContent).toContain("io_uring-7.4");
  });

  it("says Not read yet when never read, and lists the changes", () => {
    show(detail("p", { since: { at: null, changes: [{ field: "stage", text: "stage: a to b", flags: true }] } }));
    expect(screen.getByText("Not read yet")).toBeTruthy();
    expect(screen.getByText("stage: a to b")).toBeTruthy();
  });

  it("shows the date the card was read, and hides the box without changes", () => {
    const { unmount } = show(detail("p", { since: { at: 1_700_000_000, changes: [{ field: "m", text: "mail: +1", flags: true }] } }));
    expect(screen.getByText(/Since you read it on/)).toBeTruthy();
    unmount();
    show(detail("p", { since: { at: 1_700_000_000, changes: [] } }));
    expect(screen.queryByText(/Since you read it/)).toBeNull();
    expect(screen.queryByText("Not read yet")).toBeNull();
  });

  it("skips and unskips a series", async () => {
    const { unmount } = show(detail("p", { branches: [{ series: "6.1.y", skipped: false, rows: [row()] }] }));
    await userEvent.click(screen.getByText("won't backport"));
    expect(act).toHaveBeenCalledWith("skip", { series: "6.1.y" });
    unmount();
    show(detail("p", { branches: [{ series: "6.1.y", skipped: true, rows: [row({ state: "skipped" })] }] }));
    await userEvent.click(screen.getByText("backport again"));
    expect(act).toHaveBeenCalledWith("unskip", { series: "6.1.y" });
  });

  it("folds prerequisites after 8", async () => {
    const pre: Prereq[] = Array.from({ length: 10 }, (_, i) => (
      { sha: `s${i}`, subject: "x", tag: null, stable: false, text: `prereq-${i}` }));
    show(detail("p", { branches: [{ series: "6.1.y", skipped: false, rows: [row({ prereqs: pre })] }] }));
    expect(screen.getByText("prereq-7")).toBeTruthy();
    expect(screen.queryByText("prereq-8")).toBeNull();
    await userEvent.click(screen.getByText(/show all/));
    expect(screen.getByText("prereq-9")).toBeTruthy();
  });

  it("shows Fixes, Cc, FAILED mails and the hint", () => {
    show(detail("p", {
      commits: [{ sha: "c1", subject: "s", where: null, stage: "accepted", release: null, cc: "stable",
        fixes: [{ sha: "84eacf177faa", release: "v6.12-rc1", known: true }] }],
      branches: [{ series: "6.1.y", skipped: false, rows: [row()] }],
      failed: [{ series: "6.1.y", date: "2026-11-01", url: "https://x/f" }], hint: "a hint",
    }));
    expect(screen.getByText(/84eacf177faa/)).toBeTruthy();
    expect(screen.getByText(/Cc: stable/)).toBeTruthy();
    expect(screen.getByText(/FAILED mails from stable:/).textContent).not.toContain("none");
    expect(screen.getByText("a hint")).toBeTruthy();
  });

  it("says none when no FAILED mails, lists thread and 5 history entries", () => {
    const history = Array.from({ length: 7 }, (_, i) => (
      { at: 1_700_000_000 - i * 100, changes: [{ field: "f", text: `change-${i}`, flags: false }] }));
    show(detail("p", {
      branches: [{ series: "6.1.y", skipped: false, rows: [row()] }],
      thread: [{ msgid: "m", depth: 1, date: 1_700_000_000, who: "Jens", you: false, snippet: "Applied", new: true }],
      history,
    }));
    expect(screen.getByText(/FAILED mails from stable: none/)).toBeTruthy();
    expect(screen.getByText(/Applied/)).toBeTruthy();
    expect(screen.getByText(/change-4/)).toBeTruthy();
    expect(screen.queryByText(/change-5/)).toBeNull();
  });

  it("lists commits for a non-kernel project", () => {
    show(detail("p", { project: "qemu", commits: [{ sha: "deadbeef0000", subject: "fix it", where: null,
      stage: "applied", release: "v9.0", cc: null, fixes: [] }] }));
    const c = screen.getByText("fix it").closest("div")!;
    expect(within(c).getByText(/deadbeef0000/)).toBeTruthy();
  });
});
