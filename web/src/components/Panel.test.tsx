// SPDX-License-Identifier: Apache-2.0
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../api";
import { AppContext, type AppState } from "../app-context";
import { card, detail, status } from "../fixtures";
import { defaultFilters } from "../lib/filters";
import type { Tab } from "../lib/route";
import type { Card, Detail } from "../types";
import { Panel } from "./Panel";

vi.mock("../api", async (orig) => ({ ...(await orig<typeof import("../api")>()), getPatch: vi.fn() }));
const getPatch = vi.mocked(api.getPatch);
const navigate = vi.fn();
const runAction = vi.fn();

function open(c: Card, d: Detail, tab: Tab = "overview") {
  getPatch.mockResolvedValue(d);
  const state: AppState = {
    status: status(), patches: [c], filters: defaultFilters, route: { name: c.name, tab }, clockOffset: 0,
    navigate, reloadPatches: async () => {}, runAction,
  };
  return render(
    <AppContext.Provider value={state}><Panel height={300} onResize={() => {}} onResizeEnd={() => {}} /></AppContext.Provider>,
  );
}

beforeEach(() => {
  getPatch.mockReset();
  navigate.mockReset();
  runAction.mockReset();
  localStorage.clear();
});

describe("Panel", () => {
  it("renders nothing without a selection", () => {
    const state: AppState = {
      status: status(), patches: [], filters: defaultFilters, route: { name: null, tab: "overview" },
      clockOffset: 0, navigate, reloadPatches: async () => {}, runAction,
    };
    const { container } = render(<AppContext.Provider value={state}><Panel height={300} onResize={() => {}} onResizeEnd={() => {}} /></AppContext.Provider>);
    expect(container.textContent).toBe("");
  });

  it("opening it and switching tabs sends no POST, only the GET", async () => {
    const c = card("p", { unread: true });
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    open(c, detail("p", { unread: true }));
    await screen.findByText("Mark read");
    await userEvent.click(screen.getByText("History"));
    expect(runAction).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled(); // getPatch is mocked; nothing else goes out
    expect(getPatch).toHaveBeenCalledTimes(1);
    vi.unstubAllGlobals();
  });

  it("Mark read calls read and shows the returned card at once", async () => {
    const c = card("p", { unread: true });
    runAction.mockResolvedValue({ ...c, unread: false });
    open(c, detail("p", { unread: true }));
    await userEvent.click(await screen.findByText("Mark read"));
    expect(runAction).toHaveBeenCalledWith("p", "read", {});
    expect(await screen.findByText("Mark unread")).toBeTruthy();
    expect(getPatch).toHaveBeenCalledTimes(2); // reloaded after the action
  });

  it("Mark unread calls unread when the card is read", async () => {
    const c = card("p");
    runAction.mockResolvedValue({ ...c, unread: true });
    open(c, detail("p"));
    await userEvent.click(await screen.findByText("Mark unread"));
    expect(runAction).toHaveBeenCalledWith("p", "unread", {});
  });

  it("Hide and Unhide", async () => {
    const c = card("p");
    runAction.mockResolvedValue({ ...c, hidden: true });
    open(c, detail("p"));
    await userEvent.click(await screen.findByText("Hide"));
    expect(runAction).toHaveBeenCalledWith("p", "hide", {});
    expect(await screen.findByText("Unhide")).toBeTruthy();
    runAction.mockResolvedValue(c);
    await userEvent.click(screen.getByText("Unhide"));
    expect(runAction).toHaveBeenLastCalledWith("p", "unhide", {});
  });

  it("closes with a reason and a note", async () => {
    const c = card("p");
    runAction.mockResolvedValue({ ...c, closed: "dropped" });
    open(c, detail("p"));
    await userEvent.click(await screen.findByText("Close…"));
    await userEvent.selectOptions(screen.getByLabelText("Reason"), "dropped");
    await userEvent.type(screen.getByLabelText("Close note"), "obsolete");
    await userEvent.click(screen.getByText("Close patch"));
    expect(runAction).toHaveBeenCalledWith("p", "close", { reason: "dropped", note: "obsolete" });
  });

  it("closes without a note key when the note is empty", async () => {
    const c = card("p");
    runAction.mockResolvedValue(c);
    open(c, detail("p"));
    await userEvent.click(await screen.findByText("Close…"));
    await userEvent.click(screen.getByText("Close patch"));
    expect(runAction).toHaveBeenCalledWith("p", "close", { reason: "rejected" });
  });

  it("offers Mark applied before applied, not at or after it, not on closed", async () => {
    const stages = ["submitted", "accepted", "applied", "released"];
    const { unmount } = open(card("p", { stages, stage: "accepted" }), detail("p", { stages, stage: "accepted" }));
    await userEvent.click(await screen.findByText("Mark applied"));
    expect(runAction).toHaveBeenCalledWith("p", "mark-applied", {});
    unmount();
    const u2 = open(card("p", { stages, stage: "applied" }), detail("p", { stages, stage: "applied" }));
    await screen.findByText("Mark unread");
    expect(screen.queryByText("Mark applied")).toBeNull();
    u2.unmount();
    open(card("p", { stages, stage: "accepted", closed: "dropped" }), detail("p", { stages, stage: "accepted", closed: "dropped" }));
    await screen.findByText("Mark unread");
    expect(screen.queryByText("Mark applied")).toBeNull();
  });

  it("shows the lore link only when set", async () => {
    open(card("p"), detail("p", { lore_url: "https://lore.kernel.org/x" }));
    expect((await screen.findByText("lore ↗")).getAttribute("href")).toBe("https://lore.kernel.org/x");
  });

  it("shows an action error and keeps the panel", async () => {
    const c = card("p");
    runAction.mockRejectedValue(new api.ApiError(400, "bad reason", null));
    open(c, detail("p"));
    await userEvent.click(await screen.findByText("Hide"));
    expect((await screen.findByRole("alert")).textContent).toContain("bad reason");
  });

  it("Esc and the x button close to /", async () => {
    open(card("p"), detail("p"));
    await screen.findByText("Hide");
    await userEvent.keyboard("{Escape}");
    expect(navigate).toHaveBeenCalledWith({ name: null, tab: "overview" });
    navigate.mockReset();
    await userEvent.click(screen.getByLabelText("Close panel"));
    expect(navigate).toHaveBeenCalledWith({ name: null, tab: "overview" });
  });

  it("follows the route tab and navigates on tab clicks", async () => {
    const d = detail("p", { thread: [{ msgid: "m", depth: 0, date: 1, who: "A", you: false, snippet: "s", new: true }],
      history: [{ at: 1_700_000_000, changes: [{ field: "f", text: "found on lore", flags: false }] }] });
    open(card("p"), d, "history");
    expect(await screen.findByText("found on lore")).toBeTruthy();
    expect(screen.getByText("History").className).toContain("on");
    expect(screen.getByText(/Thread · 1/)).toBeTruthy();
    await userEvent.click(screen.getByText(/Thread · 1/));
    expect(navigate).toHaveBeenCalledWith({ name: "p", tab: "thread" });
  });

  it("shows the thread slot on the thread tab", async () => {
    open(card("p"), detail("p"), "thread");
    expect(await screen.findByTestId("thread-slot")).toBeTruthy();
  });

  it("shows a load error", async () => {
    getPatch.mockRejectedValue(new api.ApiError(404, "no such patch", null));
    const state: AppState = {
      status: status(), patches: [], filters: defaultFilters, route: { name: "zz", tab: "overview" },
      clockOffset: 0, navigate, reloadPatches: async () => {}, runAction,
    };
    render(<AppContext.Provider value={state}><Panel height={300} onResize={() => {}} onResizeEnd={() => {}} /></AppContext.Provider>);
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("no such patch"));
  });
});
