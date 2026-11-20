// SPDX-License-Identifier: Apache-2.0
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppContext, type AppState } from "../app-context";
import { card, status } from "../fixtures";
import { defaultFilters } from "../lib/filters";
import type { Card } from "../types";
import { Board } from "./Board";

const navigate = vi.fn();
function board(cards: Card[], routeName: string | null = null) {
  const state: AppState = {
    status: status(), patches: cards, filters: defaultFilters,
    route: { name: routeName, tab: "overview" }, clockOffset: 0, navigate,
    reloadPatches: async () => {}, runAction: async () => card("x"),
  };
  return render(<AppContext.Provider value={state}><Board cards={cards} /></AppContext.Provider>);
}

beforeEach(() => {
  navigate.mockClear();
  localStorage.clear();
});

describe("Board", () => {
  const cards = [card("live"), card("i1", { idle: true }), card("i2", { idle: true })];

  it("counts folded cards in the column title and hides them", () => {
    board(cards);
    expect(screen.getByText("Submitted · 3")).toBeTruthy();
    expect(screen.getByText("Reviewed · 0")).toBeTruthy();
    expect(screen.queryByText("i1")).toBeNull();
    expect(screen.getByText("live")).toBeTruthy();
  });

  it("expands +2 idle in place, dimmed, and remembers it", async () => {
    board(cards);
    await userEvent.click(screen.getByText("+2 idle"));
    expect(screen.getByText("i1")).toBeTruthy();
    expect(screen.getByText("i2")).toBeTruthy();
    expect(screen.getByText("i1").closest(".crd")!.className).toContain("idle");
    expect(screen.getByText("Submitted · 3")).toBeTruthy();
    expect(localStorage.getItem("patchtrail.folds")).toContain("submitted:idle");
  });

  it("starts with remembered folds open", () => {
    localStorage.setItem("patchtrail.folds", JSON.stringify({ "submitted:idle": true }));
    board(cards);
    expect(screen.getByText("i1")).toBeTruthy();
  });

  it("copes with unusable storage", async () => {
    const g = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("no"); });
    const s = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("no"); });
    board(cards);
    await userEvent.click(screen.getByText("+2 idle"));
    expect(screen.getByText("i1")).toBeTruthy();
    g.mockRestore();
    s.mockRestore();
  });

  it("shows an older fold", async () => {
    board([card("fin", { finished: true, finished_at: 1 })]);
    await userEvent.click(screen.getByText("+1 older"));
    expect(screen.getByText("fin")).toBeTruthy();
  });

  it("routes to the patch on click and marks the selected card", async () => {
    const { container } = board(cards, "live");
    expect(container.querySelector(".crd.sel")).toBeTruthy();
    await userEvent.click(screen.getByText("live"));
    expect(navigate).toHaveBeenCalledWith({ name: "live", tab: "overview" });
  });
});
